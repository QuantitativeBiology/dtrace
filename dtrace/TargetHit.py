#!/usr/bin/env python
# Copyright (C) 2019 Emanuel Goncalves

import textwrap
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.stats import pearsonr
from DTracePlot import DTracePlot
from Associations import Association
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import ShuffleSplit


class TargetHit(DTracePlot):
    def __init__(self, target, lmm_dcrispr, lmm_dgexp, lmm_comb, fdr=.1):
        super().__init__()

        self.dinfo = ['DRUG_ID', 'DRUG_NAME', 'VERSION']

        self.fdr = fdr
        self.target = target

        self.lmm_dcrispr = lmm_dcrispr
        self.lmm_dgexp = lmm_dgexp
        self.lmm_comb = lmm_comb

        self.drugs = list({
            tuple(d) for d in self.lmm_dcrispr[self.lmm_dcrispr['DRUG_TARGETS'] == self.target][self.dinfo].values
        })

    def top_associations_barplot(self):
        # Filter for signif associations
        df = self.lmm_dcrispr \
            .query(f"(fdr < {self.fdr}) & (DRUG_TARGETS == '{self.target}')") \
            .sort_values('fdr') \
            .groupby(['DRUG_NAME', 'GeneSymbol']) \
            .first() \
            .sort_values('fdr') \
            .reset_index()
        df = df.assign(logpval=-np.log10(df['pval']).values)

        # Drug order
        order = list(df.groupby('DRUG_NAME')['fdr'].min().sort_values().index)

        # Build plot dataframe
        df_, xpos = [], 0
        for i, drug_name in enumerate(order):
            df_drug = df[df['DRUG_NAME'] == drug_name]
            df_drug = df_drug.assign(xpos=np.arange(xpos, xpos + df_drug.shape[0]))

            xpos = xpos + df_drug.shape[0] + 1

            df_.append(df_drug)

        df = pd.concat(df_).reset_index()

        # Plot
        fig, ax = plt.subplots(1, 1)

        plot_df = df.query("target != 'T'")
        ax.bar(plot_df['xpos'], plot_df['logpval'], .8, color=self.PAL_DTRACE[2], align='center', zorder=5, linewidth=0)

        plot_df = df.query("target == 'T'")
        ax.bar(plot_df['xpos'], plot_df['logpval'], .8, color=self.PAL_DTRACE[0], align='center', zorder=5, linewidth=0)

        for k, v in df.groupby('DRUG_NAME')['xpos'].min().sort_values().to_dict().items():
            ax.text(v -1.2, 0.1, textwrap.fill(k, 15), va='bottom', fontsize=8, zorder=10, rotation='vertical', color=self.PAL_DTRACE[2])

        for g, p in df[['GeneSymbol', 'xpos']].values:
            ax.text(p, 0.1, g, ha='center', va='bottom', fontsize=8, zorder=10, rotation='vertical', color='white')

        for x, y, t, b in df[['xpos', 'logpval', 'target', 'beta']].values:
            c = self.PAL_DTRACE[0] if t == 'T' else self.PAL_DTRACE[2]

            ax.text(x, y + 0.25, t, color=c, ha='center', fontsize=6, zorder=10)
            ax.text(x, -2.5, f'{b:.1f}', color=c, ha='center', fontsize=6, rotation='vertical', zorder=10)

        sns.despine(right=True, top=True, ax=ax)
        ax.axes.get_xaxis().set_ticks([])

    def plot_target_drugs_corr(self, data, gene, order=None):
        if order is None:
            order = [
                tuple(d) for d in self.lmm_dcrispr
                    .query(f"(DRUG_TARGETS == '{self.target}') & (GeneSymbol == '{gene}')")[self.dinfo].values
            ]

        fig, axs = plt.subplots(1, len(order), sharey='all')

        for i, d in enumerate(order):
            plot_df = pd.concat([
                data.drespo.loc[d].rename('drug'),
                data.crispr.loc[gene].rename('crispr'),
                data.samplesheet.samplesheet['institute']
            ], axis=1, sort=False).dropna()

            for t, df in plot_df.groupby('institute'):
                axs[i].scatter(
                    x=df['drug'], y=df['crispr'], edgecolor='w', lw=.1, s=5, color=self.PAL_DTRACE[2],
                    marker=self.MARKERS[t], label=t, alpha=.8
                )

            sns.regplot(
                'drug', 'crispr', data=plot_df, line_kws=dict(lw=1., color=self.PAL_DTRACE[0]), marker='',
                truncate=True, ax=axs[i]
            )

            #
            beta, fdr = self.lmm_dcrispr.query(f"GeneSymbol == '{gene}'").set_index(self.dinfo).loc[d, ['beta', 'fdr']].values
            annot_text = f'b={beta:.2g}, p={fdr:.1e}'
            axs[i].text(.95, .05, annot_text, fontsize=4, transform=axs[i].transAxes, ha='right')

            #
            dmax = np.log(data.drespo_obj.maxconcentration[d])
            axs[i].axvline(dmax, ls='-', lw=0.1, c=self.PAL_DTRACE[1], zorder=0)

            #
            axs[i].axhline(-0.5, ls='-', lw=0.1, c=self.PAL_DTRACE[1], zorder=0)

            #
            axs[i].set_ylabel(f'{gene}\n(scaled log2 FC)' if i == 0 else '')
            axs[i].set_xlabel(f'Drug-response\n(ln IC50)')
            axs[i].set_title(d[1])

        plt.subplots_adjust(bottom=0.15, wspace=0.05)
        plt.gcf().set_size_inches(1 * len(order), 1.)

    def plot_drug_crispr_gexp(self, drug_targets):
        targets = pd.Series([DTracePlot.PAL_DTRACE[i] for i in [0, 2, 3]], index=drug_targets)

        plot_df = self.lmm_comb[self.lmm_comb['CRISPR_DRUG_TARGETS'].isin(targets.index)].reset_index()
        plot_df = plot_df[plot_df['GeneSymbol'] == plot_df['CRISPR_DRUG_TARGETS']]

        ax = plt.gca()

        for target, df in plot_df.groupby('CRISPR_DRUG_TARGETS'):
            ax.scatter(
                df['CRISPR_beta'], df['GExp_beta'], label=target, color=targets[target], edgecolor='white', lw=.3,
                zorder=1
            )

            df_signif = df.query('(CRISPR_fdr < .1) & (GExp_fdr < .1)')
            df_signif_any = df.query('(CRISPR_fdr < .1) | (GExp_fdr < .1)')

            if df_signif.shape[0] > 0:
                ax.scatter(df_signif['CRISPR_beta'], df_signif['GExp_beta'], color='white', marker='$X$', lw=.3,
                           label=None, zorder=1)

            elif df_signif_any.shape[0] > 0:
                ax.scatter(df_signif_any['CRISPR_beta'], df_signif_any['GExp_beta'], color='white', marker='$/$', lw=.3,
                           label=None, zorder=1)

        ax.axhline(0, ls='-', lw=0.1, c=DTracePlot.PAL_DTRACE[1], zorder=0)
        ax.axvline(0, ls='-', lw=0.1, c=DTracePlot.PAL_DTRACE[1], zorder=0)

        ax.legend(loc=3, frameon=False, prop={'size': 5}).get_title().set_fontsize('5')

        ax.set_xlabel('CRISPR beta')
        ax.set_ylabel('GExp beta')

        ax.set_title('LMM Drug-response model')

    def lm_drug_train(self, y, x, drug, n_splits=1000, test_size=.3):
        y = y[x.index].dropna()
        x = x.loc[y.index]

        df = []
        for train, test in ShuffleSplit(n_splits=n_splits, test_size=test_size).split(x, y):
            lm = RidgeCV().fit(x.iloc[train], y.iloc[train])

            r2 = lm.score(x.iloc[test], y.iloc[test])

            df.append(list(drug) + [r2] + list(lm.coef_))

        return pd.DataFrame(df, columns=self.dinfo + ['r2'] + list(x.columns))

    def predict_drugresponse(self, data, features):
        xss = {
            'CRISPR+GEXP': pd.concat([
                data.crispr.loc[features].T.add_prefix('CRISPR_'),
                data.gexp.loc[features].T.add_prefix('GExp_')
            ], axis=1, sort=False).dropna(),

            'CRISPR': data.crispr.loc[features].T.add_prefix('CRISPR_').dropna(),

            'GEXP': data.gexp.loc[features].T.add_prefix('GExp_').dropna()
        }

        drug_lms = []

        for ftype in xss:
            print(f'ftype = {ftype}')

            xs = xss[ftype]
            xs = pd.DataFrame(StandardScaler().fit_transform(xs), index=xs.index, columns=xs.columns)

            lm_df = pd.concat([self.lm_drug_train(data.drespo.loc[d], xs, d) for d in self.drugs])
            lm_df['ftype'] = ftype

            drug_lms.append(lm_df)

        drug_lms = pd.concat(drug_lms, sort=False)

        return drug_lms

    def predict_r2_barplot(self, drug_lms):
        order = list(
            drug_lms.query(f"ftype == 'CRISPR+GEXP'").groupby(self.dinfo)['r2'].median().sort_values(ascending=False).reset_index()['DRUG_NAME']
        )

        pal = pd.Series([DTracePlot.PAL_DTRACE[i] for i in [0, 2, 3]], index=['CRISPR', 'CRISPR+GEXP', 'GEXP'])

        sns.barplot(
            'r2', 'DRUG_NAME', 'ftype', data=drug_lms, order=order, palette=pal, orient='h', errwidth=.5, saturation=1.,
            lw=0, hue_order=pal.index
        )

        plt.axvline(0, ls='-', lw=.3, c=DTracePlot.PAL_DTRACE[2], zorder=0)

        plt.xlabel('R-squared')
        plt.ylabel('')

        plt.legend(frameon=False, prop={'size': 5}).get_title().set_fontsize('5')

    def predict_feature_plot(self, drug_lms):
        plot_df = drug_lms.drop(columns=['r2']).groupby(self.dinfo + ['ftype']).median().reset_index()
        plot_df = pd.melt(plot_df, id_vars=self.dinfo + ['ftype']).dropna()
        plot_df['variable'] = [f"{i.split('_')[1]} ({i.split('_')[0]})" for i in plot_df['variable']]

        order = list(plot_df.groupby('variable')['value'].median().sort_values(ascending=False).index)

        pal = pd.Series([DTracePlot.PAL_DTRACE[i] for i in [0, 2, 3]], index=['CRISPR', 'CRISPR+GEXP', 'GEXP'])

        sns.stripplot(
            'value', 'variable', 'ftype', data=plot_df, order=order, orient='h', edgecolor='white', linewidth=.5, s=3,
            palette=pal, hue_order=pal.index
        )

        plt.axvline(0, ls='-', lw=.3, c=DTracePlot.PAL_DTRACE[2], zorder=0)

        plt.legend(frameon=False, prop={'size': 5}).get_title().set_fontsize('5')
        plt.xlabel('Median beta')
        plt.ylabel('')


if __name__ == '__main__':
    # - Imports
    data = Association(dtype_drug='ic50')

    lmm_drug = pd.read_csv('data/drug_lmm_regressions_ic50.csv.gz')
    lmm_gexp = pd.read_csv('data/drug_lmm_regressions_ic50_gexp.csv.gz')

    lmm_combined = pd.concat([
        lmm_drug.set_index(['DRUG_ID', 'DRUG_NAME', 'VERSION', 'GeneSymbol']).add_prefix('CRISPR_'),
        lmm_gexp.set_index(['DRUG_ID', 'DRUG_NAME', 'VERSION', 'GeneSymbol']).add_prefix('GExp_'),
    ], axis=1, sort=False).dropna()

    # -
    hit = TargetHit('MCL1', lmm_dcrispr=lmm_drug, lmm_dgexp=lmm_gexp, lmm_comb=lmm_combined)

    # Top associations with MCL1i
    hit.top_associations_barplot()

    plt.ylabel('Association p-value (-log10)')
    plt.title('CRISPR associations with multiple MCL1 inhibitors')
    plt.gcf().set_size_inches(5, 1.5)
    plt.savefig('reports/hit_topbarplot.pdf', bbox_inches='tight', transparent=True)
    plt.close('all')

    # MCL1/MARCH5 regplot with MCLi
    order = [tuple(d) for d in lmm_drug.query(f"(DRUG_TARGETS == 'MCL1') & (GeneSymbol == 'MCL1')")[hit.dinfo].values]
    for g in ['MCL1', 'MARCH5']:
        hit.plot_target_drugs_corr(data, g, order=order)

        plt.savefig(f'reports/hit_target_drugs_corr_{g}.pdf', bbox_inches='tight', transparent=True)
        plt.close('all')

    # CRISPR and Gexp betas comparison
    hit.plot_drug_crispr_gexp(['MCL1', 'BCL2', 'BCL2L1'])
    plt.gcf().set_size_inches(1.5, 1.5)
    plt.savefig(f'reports/hit_BCLi_crispr~gexp.pdf', bbox_inches='tight', transparent=True)
    plt.close('all')

    # -
    features = [
        'MARCH5', 'MCL1', 'BCL2', 'BCL2L1', 'BCL2L11', 'PMAIP1', 'BAX', 'BAK1', 'BBC3', 'BID', 'BIK', 'BAD'
    ]
    drug_lms = hit.predict_drugresponse(data, features)

    hit.predict_r2_barplot(drug_lms)
    plt.gcf().set_size_inches(2, 2.5)
    plt.savefig(f'reports/hit_rsqaured_barplot.pdf', bbox_inches='tight', transparent=True)
    plt.close('all')

    hit.predict_feature_plot(drug_lms)
    plt.gcf().set_size_inches(2.5, 3)
    plt.savefig(f'reports/hit_features_stripplot.pdf', bbox_inches='tight', transparent=True)
    plt.close('all')
