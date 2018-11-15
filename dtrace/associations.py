#!/usr/bin/env python
# Copyright (C) 2018 Emanuel Goncalves

import numpy as np
import pandas as pd
from limix.qtl import scan
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.multitest import multipletests
from dtrace.importer import DrugResponse, CRISPR, Genomic, Sample, PPI


class Association:
    def __init__(self, dtype_drug='ic50'):
        # Import
        self.samplesheet = Sample()

        self.ppi = PPI()

        self.crispr_obj = CRISPR()
        self.drespo_obj = DrugResponse()
        self.genomic_obj = Genomic()

        self.samples = list(set.intersection(
            set(self.drespo_obj.get_data().columns),
            set(self.crispr_obj.get_data().columns)
        ))
        print(f'#(Samples)={len(self.samples)}')

        # Filter
        self.crispr = self.crispr_obj.filter(subset=self.samples, scale=True)
        self.drespo = self.drespo_obj.filter(subset=self.samples, dtype=dtype_drug)
        self.genomic = self.genomic_obj.filter(subset=self.samples, min_events=5)
        print(f'#(Drugs)={self.drespo.shape[0]}; #(Genes)={self.crispr.shape[0]}; #(Genomic)={self.genomic.shape[0]}')

    def get_covariates(self):
        crispr_samples_pcs = pd.read_csv('data/crispr_pca_column_pcs.csv', index_col=0)
        drug_samples_pcs = pd.read_csv('data/drug_pca_column_pcs.csv', index_col=0)

        covariates = pd.concat([
            self.crispr_obj.qc_ess.rename('recall_essential'),
            crispr_samples_pcs['PC1'].rename('crispr_pc1'),
            drug_samples_pcs['PC1'].rename('drug_pc1'),
        ], axis=1, sort=False)

        covariates = covariates.loc[self.samples]

        return covariates

    @staticmethod
    def kinship(k):
        K = k.dot(k.T)
        K /= (K.values.diagonal().mean())
        return K

    @staticmethod
    def lmm_association_limix(y, x, m=None, k=None, add_intercept=True, lik='normal'):
        # Build matrices
        Y = y.dropna()
        # Y = pd.DataFrame(StandardScaler().fit_transform(Y), index=Y.index, columns=Y.columns)

        X = x.loc[Y.index]
        X = pd.DataFrame(StandardScaler().fit_transform(X), index=X.index, columns=X.columns)

        # Random effects matrix
        if k is None:
            K = Association.kinship(x.loc[Y.index])

        else:
            K = k.loc[Y.index, Y.index]

        # Covariates
        if m is not None:
            m = m.loc[Y.index]
            m = pd.DataFrame(StandardScaler().fit_transform(m), index=m.index, columns=m.columns)

        # Add intercept
        if add_intercept and (m is not None):
            m['intercept'] = 1

        elif add_intercept and (m is None):
            m = pd.DataFrame(np.ones((Y.shape[0], 1)), index=Y.index, columns=['intercept'])

        else:
            m = pd.DataFrame(np.zeros((Y.shape[0], 1)), index=Y.index, columns=['zeros'])

        # Linear Mixed Model
        lmm = scan(X, Y, K=K, M=m, lik=lik, verbose=False)

        return lmm, dict(x=X, y=Y, k=K, m=m)

    @staticmethod
    def multipletests_per_drug(associations, method='bonferroni', field='pval', fdr_field='fdr', index_cols=None):
        index_cols = DrugResponse.DRUG_COLUMNS if index_cols is None else index_cols

        d_unique = {tuple(i) for i in associations[index_cols].values}

        df = associations.set_index(index_cols)

        df = pd.concat([
            df.loc[i].assign(
                fdr=multipletests(df.loc[i, field], method=method)[1]
            ).rename(columns={'fdr': fdr_field}) for i in d_unique
        ]).reset_index()

        return df

    def annotate_drug_target(self, associations):
        d_targets = self.drespo_obj.get_drugtargets()

        associations['DRUG_TARGETS'] = [
            ';'.join(d_targets[d]) if d in d_targets else np.nan for d in associations['DRUG_ID']
        ]

        return associations

    @staticmethod
    def get_association(lmm_associations, drug, gene):
        return lmm_associations[
            (lmm_associations[DrugResponse.DRUG_COLUMNS[0]] == drug[0]) & \
            (lmm_associations[DrugResponse.DRUG_COLUMNS[1]] == drug[1]) & \
            (lmm_associations[DrugResponse.DRUG_COLUMNS[2]] == drug[2]) & \
            (lmm_associations['GeneSymbol'] == gene)
        ]

    @staticmethod
    def __lmm_single_associations(y, x, m=None, k=None, expand_drug_id=True):
        lmm, params = Association.lmm_association_limix(y, x, m, k)

        df = pd.DataFrame(
            dict(beta=lmm.variant_effsizes.ravel(), pval=lmm.variant_pvalues.ravel(), GeneSymbol=params['x'].columns)
        )

        drug = y.columns[0]

        if expand_drug_id:
            df = df.assign(DRUG_ID=drug[0])
            df = df.assign(DRUG_NAME=drug[1])
            df = df.assign(VERSION=drug[2])

        else:
            df = df.assign(DRUG_ID=drug)

        df = df.assign(n_samples=params['y'].shape[0])

        return df

    def lmm_single_associations(self, method='bonferroni'):
        # - Kinship matrix (random effects)
        k = self.kinship(self.crispr.T)
        m = self.get_covariates()

        # - Single feature linear mixed regression
        # Association
        lmm_single = pd.concat([
            self.__lmm_single_associations(self.drespo.loc[[d]].T, self.crispr.T, k=k, m=m) for d in self.drespo.index
        ])

        # Multiple p-value correction
        lmm_single = self.multipletests_per_drug(lmm_single, field='pval', method=method)

        # Annotate drug target
        lmm_single = self.annotate_drug_target(lmm_single)

        # Annotate association distance to target
        lmm_single = self.ppi.ppi_annotation(
            lmm_single, ppi_type='string', ppi_kws=dict(score_thres=900), target_thres=3
        )

        # Sort p-values
        lmm_single = lmm_single.sort_values(['fdr', 'pval'])

        return lmm_single

    @staticmethod
    def __lmm_robust_association(association, y1, y2, x, min_events):
        samples = list(x)

        # Build drug measurement matrix
        Y1 = y1.loc[[tuple(association[:3])], samples].T.dropna()

        # Build CRISPR measurement matrix
        Y2 = y2.loc[[association[3]], Y1.index].T

        # Build genomic feature matrix
        X = x[Y1.index].T
        X = X.loc[:, X.sum() >= min_events]

        # Random effects matrix
        K = x[Y1.index].T
        K = K.dot(K.T)
        K /= (K.values.diagonal().mean())

        # Linear Mixed Model
        lmm_y1 = scan(X, Y1, K=K, lik='normal', verbose=False)
        lmm_y2 = scan(X, Y2, K=K, lik='normal', verbose=False)

        # Assemble output
        df = pd.DataFrame(dict(
            beta_drug=lmm_y1.variant_effsizes.ravel(),
            pval_drug=lmm_y1.variant_pvalues.ravel(),
            beta_crispr=lmm_y2.variant_effsizes.ravel(),
            pval_crispr=lmm_y2.variant_pvalues.ravel(),
            Genetic=X.columns,
            n_events=X.sum().values
        ))

        df = df.assign(DRUG_ID=association[0])
        df = df.assign(DRUG_NAME=association[1])
        df = df.assign(VERSION=association[2])
        df = df.assign(GeneSymbol=association[3])
        df = df.assign(n_samples=Y1.shape[0])

        return df

    def lmm_robust_association(self, lmm_single_associations, fdr_thres=.1, min_events=5):
        lmm_res_signif = lmm_single_associations.query(f'fdr < {fdr_thres}')
        print(f'#(Significant associations) = {lmm_res_signif.shape[0]}')

        lmmrobust = pd.concat([
            self.__lmm_robust_association(a, self.drespo, self.crispr, self.genomic, min_events)
            for a in lmm_res_signif[DrugResponse.DRUG_COLUMNS + ['GeneSymbol']].values
        ])

        lmmrobust = self.multipletests_per_drug(lmmrobust, field='pval_drug', fdr_field=f'fdr_drug')
        lmmrobust = self.multipletests_per_drug(lmmrobust, field='pval_crispr', fdr_field='fdr_crispr')

        return lmmrobust


if __name__ == '__main__':
    dtype = 'ic50'

    assoc = Association(dtype_drug=dtype)

    lmm_dsingle = assoc.lmm_single_associations()
    lmm_dsingle\
        .sort_values(['pval', 'fdr'])\
        .to_csv(f'data/drug_lmm_regressions_{dtype}.csv.gz', index=False, compression='gzip')

    lmm_robust = assoc.lmm_robust_association(lmm_dsingle)
    lmm_robust\
        .sort_values(['fdr_drug', 'pval_drug'])\
        .to_csv(f'data/drug_lmm_regressions_robust_{dtype}.csv.gz', index=False, compression='gzip')
