#!/usr/bin/env python
# Copyright (C) 2018 Emanuel Goncalves

import igraph
import warnings
import numpy as np
import pandas as pd
import crispy as cy


class DrugResponse:
    SAMPLE_COLUMNS = ['model_id']
    DRUG_COLUMNS = ['DRUG_ID', 'DRUG_NAME', 'VERSION']

    DRUG_OWNERS = ['AZ', 'GDSC', 'MGH', 'NCI.Pommier', 'Nathaneal.Gray']

    def __init__(
            self,
            drugsheet_file='data/meta/drugsheet_20181114.xlsx',
            drugresponse_file_v17='data/drug/screening_set_384_all_owners_fitted_data_20180308_updated.csv',
            drugresponse_file_rs='data/drug/fitted_rapid_screen_1536_v1.2.1_20181026_updated.csv',
    ):
        self.drugsheet = pd.read_excel(drugsheet_file, index_col=0)

        # Import and Merge drug response matrices
        self.d_v17 = pd.read_csv(drugresponse_file_v17).assign(VERSION='v17')
        self.d_rs = pd.read_csv(drugresponse_file_rs).assign(VERSION='RS')

        self.drugresponse = dict()
        for index_value, n in [('ln_IC50', 'ic50'), ('AUC', 'auc')]:
            d_v17_matrix = pd.pivot_table(
                self.d_v17, index=self.DRUG_COLUMNS, columns=self.SAMPLE_COLUMNS, values=index_value
            )

            d_vrs_matrix = pd.pivot_table(
                self.d_rs, index=self.DRUG_COLUMNS, columns=self.SAMPLE_COLUMNS, values=index_value
            )

            df = pd.concat([d_v17_matrix, d_vrs_matrix], axis=0, sort=False)

            self.drugresponse[n] = df.copy()

        # Read drug max concentration
        self.maxconcentration = pd.concat([
            self.d_rs.groupby(self.DRUG_COLUMNS)['maxc'].min(),
            self.d_v17.groupby(self.DRUG_COLUMNS)['maxc'].min()
        ], sort=False).sort_values()

    def get_drugtargets(self):
        d_targets = self.drugsheet['Target Curated'].dropna().to_dict()
        d_targets = {k: {t.strip() for t in d_targets[k].split(';')} for k in d_targets}
        return d_targets

    def get_data(self, dtype='ic50'):
        return self.drugresponse[dtype].copy()

    def filter(
            self, dtype='ic50', subset=None, min_events=3, min_meas=0.75, max_c=0.5, filter_max_concentration=True,
            filter_owner=True, filter_combinations=True
    ):
        # Drug max screened concentration
        df = self.get_data(dtype='ic50')
        d_maxc = np.log(self.maxconcentration * max_c)

        # - Filters
        # Subset samples
        if subset is not None:
            df = df.loc[:, df.columns.isin(subset)]

        # Filter by mininum number of observations
        df = df[df.count(1) > (df.shape[1] * min_meas)]

        # Filter by max screened concentration
        if filter_max_concentration:
            df = df[[sum(df.loc[i] < d_maxc.loc[i]) >= min_events for i in df.index]]

        # Filter by owners
        if filter_owner:
            ds = self.drugsheet[self.drugsheet['Owner'].isin(self.DRUG_OWNERS)]
            df = df[[i[0] in ds.index for i in df.index]]

        # Filter combinations
        if filter_combinations:
            df = df[[' + ' not in i[1] for i in df.index]]

        return self.get_data(dtype).loc[df.index, df.columns]

    def is_in_druglist(self, drug_ids):
        return np.all([d in self.drugsheet.index for d in drug_ids])

    def is_same_drug(self, drug_id_1, drug_id_2):
        """
        Check if 2 Drug IDs are represent the same drug by checking if Name or Synonyms are the same.

        :param drug_id_1:
        :param drug_id_2:
        :return: Bool
        """

        if drug_id_1 not in self.drugsheet:
            warnings.warn('Drug ID {} not in drug list'.format(drug_id_1))
            return False

        if drug_id_2 not in self.drugsheet:
            warnings.warn('Drug ID {} not in drug list'.format(drug_id_2))
            return False

        drug_names = {d: self.get_drug_names(d) for d in [drug_id_1, drug_id_2]}

        return len(drug_names[drug_id_1].intersection(drug_names[drug_id_2])) > 0

    def get_drug_names(self, drug_id):
        """
        From a Drug ID get drug Name and Synonyms.

        :param drug_id:
        :return:
        """

        if drug_id not in self.drugsheet.index:
            print('{} Drug ID not in drug list'.format(drug_id))
            return None

        drug_name = [self.drugsheet.loc[drug_id, 'Name']]

        drug_synonyms = self.drugsheet.loc[drug_id, 'Synonyms']
        drug_synonyms = [] if str(drug_synonyms).lower() == 'nan' else drug_synonyms.split(', ')

        return set(drug_name + drug_synonyms)

    @staticmethod
    def growth_corr(df, growth):
        samples = list(set(growth.dropna().index).intersection(df.columns))

        g_corr = df[samples].T\
            .corrwith(growth[samples])\
            .sort_values()\
            .rename('corr')\
            .reset_index()

        return g_corr


class CRISPR:
    LOW_QUALITY_SAMPLES = ['SIDM00096']

    def __init__(
            self, datadir='data/crispr/',
            sanger_fc_file='sanger_depmap18_fc_corrected.csv',
            sanger_qc_file='sanger_depmap18_fc_ess_aucs.csv',
            broad_fc_file='broad_depmap18q4_fc_corrected.csv',
            broad_qc_file='broad_depmap18q4_fc_ess_aucs.csv'
    ):
        self.DATADIR = datadir

        self.SANGER_FC_FILE = sanger_fc_file
        self.SANGER_QC_FILE = sanger_qc_file

        self.BROAD_FC_FILE = broad_fc_file
        self.BROAD_QC_FILE = broad_qc_file

        self.crispr, self.institute = self.__merge_matricies()

        self.crispr = self.crispr.drop(columns=self.LOW_QUALITY_SAMPLES)

        self.qc_ess = self.__merge_qc_arrays()

    def __merge_qc_arrays(self):
        gdsc_qc = pd.Series.from_csv(f'{self.DATADIR}/{self.SANGER_QC_FILE}')
        broad_qc = pd.Series.from_csv(f'{self.DATADIR}/{self.BROAD_QC_FILE}')

        qcs = pd.concat([
            gdsc_qc[self.institute[self.institute == 'Sanger'].index],
            broad_qc[self.institute[self.institute == 'Broad'].index]
        ])

        return qcs

    def __merge_matricies(self):
        gdsc_fc = pd.read_csv(f'{self.DATADIR}/{self.SANGER_FC_FILE}', index_col=0).dropna()
        broad_fc = pd.read_csv(f'{self.DATADIR}/{self.BROAD_FC_FILE}', index_col=0).dropna()

        genes = list(set(gdsc_fc.index).intersection(broad_fc.index))

        merged_matrix = pd.concat([
            gdsc_fc.loc[genes],
            broad_fc.loc[genes, [i for i in broad_fc if i not in gdsc_fc.columns]]
        ], axis=1, sort=False)

        institute = pd.Series({s: 'Sanger' if s in gdsc_fc.columns else 'Broad' for s in merged_matrix})

        return merged_matrix, institute

    def get_data(self, scale=True):
        df = self.crispr.copy()

        if scale:
            df = self.scale(df)

        return df

    def filter(
            self, subset=None, scale=True, abs_thres=None, drop_core_essential=False, min_events=5,
            drop_core_essential_broad=False
    ):
        df = self.get_data(scale=True)

        # - Filters
        # Subset matrices
        if subset is not None:
            df = df.loc[:, df.columns.isin(subset)]

        # Filter by scaled scores
        if abs_thres is not None:
            df = df[(df.abs() > abs_thres).sum(1) >= min_events]

        # Filter out core essential genes
        if drop_core_essential:
            df = df[~df.index.isin(cy.Utils.get_adam_core_essential())]

        if drop_core_essential_broad:
            df = df[~df.index.isin(cy.Utils.get_broad_core_essential())]

        # - Subset matrices
        return self.get_data(scale=scale).loc[df.index].reindex(columns=df.columns)

    @staticmethod
    def scale(df, essential=None, non_essential=None, metric=np.median):
        if essential is None:
            essential = cy.Utils.get_essential_genes(return_series=False)

        if non_essential is None:
            non_essential = cy.Utils.get_non_essential_genes(return_series=False)

        assert len(essential.intersection(df.index)) != 0, \
            'DataFrame has no index overlapping with essential list'

        assert len(non_essential.intersection(df.index)) != 0, \
            'DataFrame has no index overlapping with non essential list'

        essential_metric = metric(df.reindex(essential).dropna(), axis=0)
        non_essential_metric = metric(df.reindex(non_essential).dropna(), axis=0)

        df = df.subtract(non_essential_metric).divide(non_essential_metric - essential_metric)

        return df


class Sample:
    def __init__(
            self,
            samplesheet_file='data/meta/model_list_2018-09-28_1452.csv',
            growthrate_file='data/meta/growth_rates_rapid_screen_1536_v1.2.2_20181113.csv',
            samples_origin='data/meta/samples_origin.csv'
    ):
        self.index = 'model_id'

        self.samplesheet = pd.read_csv(samplesheet_file).dropna(subset=[self.index]).set_index(self.index)

        self.growth = pd.read_csv(growthrate_file)
        self.samplesheet['growth'] = self.growth.groupby(self.index)['GROWTH_RATE'].mean()\
            .reindex(self.samplesheet.index)

        self.institute = pd.Series.from_csv(samples_origin)
        self.samplesheet['institute'] = self.institute.reindex(self.samplesheet.index)

    def __assemble_growth_rates(self, dfile):
        # Import
        dratio = pd.read_csv(dfile, index_col=0)

        # Convert to date
        dratio['DATE_CREATED'] = pd.to_datetime(dratio['DATE_CREATED'])

        # Group growth ratios per seeding
        d_nc1 = dratio.groupby([self.index, 'SEEDING_DENSITY'])\
            .agg({'growth_rate': [np.median, 'count'], 'DATE_CREATED': [np.max]})\
            .reset_index()

        d_nc1.columns = ['_'.join(filter(lambda x: x != '', i)) for i in d_nc1]

        # Pick most recent measurements per cell line
        d_nc1 = d_nc1.iloc[d_nc1.groupby(self.index)['DATE_CREATED_amax'].idxmax()].set_index(self.index)

        return d_nc1

    def build_covariates(
            self, samples=None, discrete_vars=None, continuos_vars=None, extra_vars=None
    ):
        covariates = []

        if discrete_vars is not None:
            covariates.append(
                pd.concat([
                    pd.get_dummies(self.samplesheet[v].dropna()) for v in discrete_vars
                ], axis=1, sort=False)
            )

        if continuos_vars is not None:
            covariates.append(self.samplesheet.reindex(columns=continuos_vars))

        if extra_vars is not None:
            covariates.append(extra_vars.copy())

        if len(covariates) == 0:
            return None

        covariates = pd.concat(covariates, axis=1, sort=False)

        if samples is not None:
            covariates = covariates.loc[samples]

        return covariates


class Genomic:
    def __init__(
            self,
            mobem_file='data/genomic/PANCAN_mobem.csv', drop_factors=True, add_msi=True
    ):
        self.sample = Sample()

        idmap = self.sample.samplesheet.reset_index().dropna(subset=['COSMIC_ID', 'model_id']) \
            .set_index('COSMIC_ID')['model_id']

        mobem = pd.read_csv(mobem_file, index_col=0)
        mobem = mobem[mobem.index.astype(str).isin(idmap.index)]
        mobem = mobem.set_index(idmap[mobem.index.astype(str)].values)

        if drop_factors is not None:
            mobem = mobem.drop(columns={'TISSUE_FACTOR', 'MSI_FACTOR', 'MEDIA_FACTOR'})

        if add_msi:
            self.msi = self.sample.samplesheet.loc[mobem.index, 'msi_status']
            mobem['msi_status'] = (self.msi == 'MSI-H').astype(int)[mobem.index].values

        self.mobem = mobem.astype(int).T

    def get_data(self):
        return self.mobem.copy()

    def filter(self, subset=None, min_events=5):
        df = self.get_data()

        # Subset matrices
        if subset is not None:
            df = df.loc[:, df.columns.isin(subset)]

        # Minimum number of events
        df = df[df.sum(1) >= min_events]

        return df

    @staticmethod
    def mobem_feature_to_gene(f):
        if f.endswith('_mut'):
            genes = {f.split('_')[0]}

        elif f.startswith('gain.') or f.startswith('loss.'):
            genes = {
                g for fs in f.split('..')
                if not (fs.startswith('gain.') or fs.startswith('loss.')) for g in fs.split('.') if g != ''
            }

        else:
            raise ValueError('{} is not a valid MOBEM feature.'.format(f))

        return genes

    @staticmethod
    def mobem_feature_type(f):
        if f.endswith('_mut'):
            return 'Mutation'

        elif f.startswith('gain.'):
            return 'CN gain'

        elif f.startswith('loss.'):
            return 'CN loss'

        else:
            raise ValueError('{} is not a valid MOBEM feature.'.format(f))


class GeneExpression:
    def __init__(self, gexp_file='data/genomic/rnaseq_voom.csv.gz'):
        self.gexp = pd.read_csv(gexp_file, index_col=0)

    def get_data(self):
        return self.gexp.copy()


class PPI:
    def __init__(
            self,
            string_file='data/ppi/9606.protein.links.full.v10.5.txt',
            string_alias_file='data/ppi/9606.protein.aliases.v10.5.txt',
            biogrid_file='data/ppi/BIOGRID-ORGANISM-Homo_sapiens-3.4.157.tab2.txt'
    ):
        self.string_file = string_file
        self.string_alias_file = string_alias_file
        self.biogrid_file = biogrid_file

        self.drug_targets = DrugResponse().get_drugtargets()

    def ppi_annotation(self, df, ppi_type, ppi_kws, target_thres=4):
        df_genes, df_drugs = set(df['GeneSymbol']), set(df['DRUG_ID'])

        # PPI annotation
        if ppi_type == 'string':
            ppi = self.build_string_ppi(**ppi_kws)
        elif ppi_type == 'biogrid':
            ppi = self.build_biogrid_ppi(**ppi_kws)
        else:
            raise Exception('ppi_type not supported, choose from: string or biogrid')

        # Drug target
        d_targets = {k: self.drug_targets[k] for k in df_drugs if k in self.drug_targets}

        # Calculate distance between drugs and CRISPRed genes in PPI
        dist_d_g = self.dist_drugtarget_genes(d_targets, df_genes, ppi)

        # Annotate drug regressions
        def drug_gene_annot(d, g):
            if d not in d_targets:
                res = '-'

            elif g in d_targets[d]:
                res = 'T'

            elif d not in dist_d_g or g not in dist_d_g[d]:
                res = '-'

            else:
                res = self.ppi_dist_to_string(dist_d_g[d][g], target_thres)

            return res

        df = df.assign(target=[drug_gene_annot(d, g) for d, g in df[['DRUG_ID', 'GeneSymbol']].values])

        return df

    @staticmethod
    def dist_drugtarget_genes(drug_targets, genes, ppi):
        genes = genes.intersection(set(ppi.vs['name']))
        assert len(genes) != 0, 'No genes overlapping with PPI provided'

        dmatrix = {}

        for drug in drug_targets:
            drug_genes = drug_targets[drug].intersection(genes)

            if len(drug_genes) != 0:
                dmatrix[drug] = dict(zip(*(genes, np.min(ppi.shortest_paths(source=drug_genes, target=genes), axis=0))))

        return dmatrix

    @staticmethod
    def ppi_dist_to_string(d, target_thres):
        if d == 0:
            res = 'T'

        elif d == np.inf:
            res = '-'

        elif d < target_thres:
            res = str(int(d))

        else:
            res = '>={}'.format(target_thres)

        return res

    def build_biogrid_ppi(self, exp_type=None, int_type=None, organism=9606, export_pickle=None):
        # 'Affinity Capture-MS', 'Affinity Capture-Western'
        # 'Reconstituted Complex', 'PCA', 'Two-hybrid', 'Co-crystal Structure', 'Co-purification'

        # Import
        biogrid = pd.read_csv(self.biogrid_file, sep='\t')

        # Filter organism
        biogrid = biogrid[
            (biogrid['Organism Interactor A'] == organism) & (biogrid['Organism Interactor B'] == organism)
            ]

        # Filter non matching genes
        biogrid = biogrid[
            (biogrid['Official Symbol Interactor A'] != '-') & (biogrid['Official Symbol Interactor B'] != '-')
            ]

        # Physical interactions only
        if int_type is not None:
            biogrid = biogrid[[i in int_type for i in biogrid['Experimental System Type']]]
        print('Experimental System Type considered: {}'.format('; '.join(set(biogrid['Experimental System Type']))))

        # Filter by experimental type
        if exp_type is not None:
            biogrid = biogrid[[i in exp_type for i in biogrid['Experimental System']]]
        print('Experimental System considered: {}'.format('; '.join(set(biogrid['Experimental System']))))

        # Interaction source map
        biogrid['interaction'] = biogrid['Official Symbol Interactor A'] + '<->' + biogrid[
            'Official Symbol Interactor B']

        # Unfold associations
        biogrid = {
            (s, t) for p1, p2 in biogrid[['Official Symbol Interactor A', 'Official Symbol Interactor B']].values
            for s, t in [(p1, p2), (p2, p1)] if s != t
        }

        # Build igraph network
        # igraph network
        net_i = igraph.Graph(directed=False)

        # Initialise network lists
        edges = [(px, py) for px, py in biogrid]
        vertices = list({p for p1, p2 in biogrid for p in [p1, p2]})

        # Add nodes
        net_i.add_vertices(vertices)

        # Add edges
        net_i.add_edges(edges)

        # Simplify
        net_i = net_i.simplify()
        print(net_i.summary())

        # Export
        if export_pickle is not None:
            net_i.write_pickle(export_pickle)

        return net_i

    def build_string_ppi(self, score_thres=900, export_pickle=None):
        # ENSP map to gene symbol
        gmap = pd.read_csv(self.string_alias_file, sep='\t')
        gmap = gmap[['BioMart_HUGO' in i.split(' ') for i in gmap['source']]]
        gmap = gmap.groupby('string_protein_id')['alias'].agg(lambda x: set(x)).to_dict()
        gmap = {k: list(gmap[k])[0] for k in gmap if len(gmap[k]) == 1}
        print('ENSP gene map: ', len(gmap))

        # Load String network
        net = pd.read_csv(self.string_file, sep=' ')

        # Filter by moderate confidence
        net = net[net['combined_score'] > score_thres]

        # Filter and map to gene symbol
        net = net[[p1 in gmap and p2 in gmap for p1, p2 in net[['protein1', 'protein2']].values]]
        net['protein1'] = [gmap[p1] for p1 in net['protein1']]
        net['protein2'] = [gmap[p2] for p2 in net['protein2']]
        print('String: ', len(net))

        #  String network
        net_i = igraph.Graph(directed=False)

        # Initialise network lists
        edges = [(px, py) for px, py in net[['protein1', 'protein2']].values]
        vertices = list(set(net['protein1']).union(net['protein2']))

        # Add nodes
        net_i.add_vertices(vertices)

        # Add edges
        net_i.add_edges(edges)

        # Add edge attribute score
        net_i.es['score'] = list(net['combined_score'])

        # Simplify
        net_i = net_i.simplify(combine_edges='max')
        print(net_i.summary())

        # Export
        if export_pickle is not None:
            net_i.write_pickle(export_pickle)

        return net_i

    @staticmethod
    def ppi_corr(ppi, m_corr, m_corr_thres=None):
        """
        Annotate PPI network based on Pearson correlation between the vertices of each edge using
        m_corr data-frame and m_corr_thres (Pearson > m_corr_thress).

        :param ppi:
        :param m_corr:
        :param m_corr_thres:
        :return:
        """
        # Subset PPI network
        ppi = ppi.subgraph([i.index for i in ppi.vs if i['name'] in m_corr.index])

        # Edge correlation
        crispr_pcc = np.corrcoef(m_corr.loc[ppi.vs['name']].values)
        ppi.es['corr'] = [crispr_pcc[i.source, i.target] for i in ppi.es]

        # Sub-set by correlation between vertices of each edge
        if m_corr_thres is not None:
            ppi = ppi.subgraph_edges([i.index for i in ppi.es if abs(i['corr']) > m_corr_thres])

        print(ppi.summary())

        return ppi


if __name__ == '__main__':
    crispr = CRISPR()
    samples = Sample()
    genomic = Genomic()
    drug_response = DrugResponse()

    samples = list(set.intersection(
        set(drug_response.get_data().columns),
        set(crispr.get_data().columns)
    ))
    print(f'#(Samples)={len(samples)}')

    drug_respo = drug_response.filter(subset=samples, min_meas=0.75)
    print(f'Spaseness={(1 - drug_respo.count().sum() / np.prod(drug_respo.shape)) * 100:.1f}%')
