#!/usr/bin/env python
# Copyright (C) 2018 Emanuel Goncalves

import pydot
import dtrace
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from dtrace import get_drugtargets
from dtrace.analysis import PAL_DTRACE
from analysis.plot.corrplot import plot_corrplot
from dtrace.assemble.assemble_ppi import build_string_ppi
from statsmodels.distributions.empirical_distribution import ECDF
from dtrace.associations import ppi_annotation, corr_drugtarget_gene, ppi_corr, DRUG_INFO_COLUMNS


def get_edges(ppi, nodes, corr_thres, norder):
    # Subset network
    ppi_sub = ppi.copy().subgraph_edges([e for e in ppi.es if abs(e['corr']) >= corr_thres])

    # Nodes that are contained in the network
    nodes = {v for v in nodes if v in ppi_sub.vs['name']}
    assert len(nodes) > 0, 'None of the nodes is contained in the PPI'

    # Nodes neighborhood
    neighbor_nodes = {v for n in nodes for v in ppi_sub.neighborhood(n, order=norder)}

    # Build subgraph
    subgraph = ppi_sub.subgraph(neighbor_nodes)

    # Build data-frame
    nodes_df = pd.DataFrame([{
        'source': subgraph.vs[e.source]['name'],
        'target': subgraph.vs[e.target]['name'],
        'r': e['corr']
    } for e in subgraph.es]).sort_values('r')

    return nodes_df


def plot_ppi(d_id, lmm_drug, corr_thres=0.2, fdr_thres=0.05, norder=1):
    # Build data-set
    d_signif = lmm_drug.query('DRUG_ID_lib == {} & fdr < {}'.format(d_id, fdr_thres))
    d_ppi_df = get_edges(ppi, list(d_signif['GeneSymbol']), corr_thres, norder)

    # Build graph
    graph = pydot.Dot(graph_type='graph', pagedir='TR')

    kws_nodes = dict(style='"rounded,filled"', shape='rect', color=PAL_DTRACE[1], penwidth=2, fontcolor='white')
    kws_edges = dict(fontsize=9, fontcolor=PAL_DTRACE[2], color=PAL_DTRACE[2])

    for s, t, r in d_ppi_df[['source', 'target', 'r']].values:
        # Add source node
        fs = 15 if s in d_signif['GeneSymbol'].values else 9
        fc = PAL_DTRACE[0 if d_id in d_targets and s in d_targets[d_id] else 2]

        source = pydot.Node(s, fillcolor=fc, fontsize=fs, **kws_nodes)
        graph.add_node(source)

        # Add target node
        fc = PAL_DTRACE[0 if d_id in d_targets and t in d_targets[d_id] else 2]
        fs = 15 if t in d_signif['GeneSymbol'].values else 9

        target = pydot.Node(t, fillcolor=fc, fontsize=fs, **kws_nodes)
        graph.add_node(target)

        # Add edge
        edge = pydot.Edge(source, target, label='{:.2f}'.format(r), **kws_edges)
        graph.add_edge(edge)

    return graph


if __name__ == '__main__':
    # - Imports
    # Data-sets
    mobems = dtrace.get_mobem()
    drespo = dtrace.get_drugresponse()

    crispr = dtrace.get_crispr(dtype='both')
    crispr_logfc = dtrace.get_crispr(dtype='logFC', scale=True)

    samples = list(set(mobems).intersection(drespo).intersection(crispr))
    print('#(Samples) = {}'.format(len(samples)))

    ss = dtrace.get_samplesheet()

    # Drug max screened concentration
    d_maxc = pd.read_csv(dtrace.DRUG_RESPONSE_MAXC, index_col=[0, 1, 2])

    # Linear regressions
    lmm_drug = pd.read_csv(dtrace.LMM_ASSOCIATIONS)
    lmm_drug = ppi_annotation(lmm_drug, ppi_type=build_string_ppi, ppi_kws=dict(score_thres=900), target_thres=3)
    lmm_drug = corr_drugtarget_gene(lmm_drug)

    # Drug target
    d_targets = get_drugtargets()

    # PPI
    ppi = build_string_ppi(score_thres=900)
    ppi = ppi_corr(ppi, crispr_logfc)

    # - Top associations
    lmm_drug.sort_values('fdr')

    lmm_drug[lmm_drug['DRUG_NAME'] == 'MCL1_1284'].sort_values(['fdr', 'pval']).head(60)

    idx, cor_thres, norder = 934059, 0.3, 3

    # -
    d = 'MCL1_1284'

    plot_df = pd.concat([
        crispr_logfc.loc['MCL1', samples],
        crispr_logfc.loc['MARCH5', samples],
        drespo.loc[(d_id, d_name, d_screen), samples].rename('drug')
    ], axis=1).dropna()
    plot_df = plot_df.assign(s=(1 - ECDF(plot_df['drug'])(plot_df['drug'])) * 10)

    plt.scatter(plot_df['MCL1'], plot_df['MARCH5'], s=plot_df['s'], color=PAL_DTRACE[2])
    plt.gcf().set_size_inches(2., 2.)
    plt.savefig('reports/mcl_scatter.pdf', bbox_inches='tight')
    plt.close('all')

    #
    d_gene = 'MARCH5'
    d_id, d_name, d_screen = 2125, 'Mcl1_7350', 'RS'

    for d_id, d_name, d_screen in lmm_drug[lmm_drug['GeneSymbol'] == 'MCL1'].sort_values('fdr').head(5)[DRUG_INFO_COLUMNS].values:
        name = '{} [{}, {}]'.format(d_name, d_id, d_screen)

        plot_df = pd.concat([
            crispr_logfc.loc[d_gene].rename('crispr'), drespo.loc[(d_id, d_name, d_screen)].rename('drug')
        ], axis=1).dropna().sort_values('drug')

        plot_corrplot('crispr', 'drug', plot_df, add_hline=True, lowess=False)
        plt.axhline(np.log(d_maxc.loc[(d_id, d_name, d_screen), 'max_conc_micromolar']), lw=.3, color=PAL_DTRACE[2], ls='--')

        plt.xlabel(d_gene)
        plt.ylabel(name)

        plt.gcf().set_size_inches(2., 2.)
        plt.savefig('reports/{}_corrplot_{}.pdf'.format(d_gene, name), bbox_inches='tight')
        plt.close('all')

    #
    plot_df = pd.concat([
        crispr_logfc.loc['MCL1'], crispr_logfc.loc['MARCH5']
    ], axis=1).dropna()

    plot_corrplot('MCL1', 'DBR1', plot_df, add_hline=True, lowess=False)

    plt.gcf().set_size_inches(2., 2.)
    plt.savefig('reports/corrplot_MCL1_MARCH5.pdf'.format(d_gene, name), bbox_inches='tight')
    plt.close('all')

    #
    plot_df = crispr_logfc.T.corrwith(crispr_logfc.loc['MCL1']).sort_values(ascending=False)
    plot_df = plot_df.head(10).rename('r').reset_index()

    sns.barplot('r', 'GeneSymbol', data=plot_df, color=PAL_DTRACE[2])
    plt.gcf().set_size_inches(1, 2)
    plt.savefig('reports/MCL1_barplot.pdf'.format(d_gene, name), bbox_inches='tight')
    plt.close('all')

    # - Top correlation examples
    indices = [
        (934059, 0.2, 1),
        (1048516, 0.3, 2),
        (134251, 0.3, 2),
        (232252, 0.3, 2),
        (1020056, 0.4, 2),
        (1502618, .4, 2),
        (21812, 0.3, 2),
        (1406940, 0.3, 2),
        (1334186, 0.3, 2),
        (289994, 0.3, 2),
        (850144, 0.3, 2),
        (777907, 0.3, 2),
        (229423, 0.3, 2)
    ]

    for idx, cor_thres, norder in indices:
        d_id, d_name, d_screen, d_gene = lmm_drug.loc[idx, ['DRUG_ID_lib', 'DRUG_NAME', 'VERSION', 'GeneSymbol']].values
        name = 'Drug={}, Gene={} [{}, {}]'.format(d_name, d_gene, d_id, d_screen)

        # Drug ~ CRISPR correlation
        x, y = '{}'.format(d_gene), '{}'.format(d_name)

        plot_df = pd.concat([
            crispr_logfc.loc[d_gene].rename(x), drespo.loc[(d_id, d_name, d_screen)].rename(y)
        ], axis=1).dropna().sort_values(x)

        plot_corrplot(x, y, plot_df, add_hline=True, lowess=False)
        plt.axhline(np.log(d_maxc.loc[(d_id, d_name, d_screen), 'max_conc_micromolar']), lw=.3, color=PAL_DTRACE[2], ls='--')

        plt.gcf().set_size_inches(2., 2.)
        plt.savefig('reports/lmm_association_corrplot_{}.pdf'.format(name), bbox_inches='tight')
        plt.close('all')

        # Drug network
        graph = plot_ppi(d_id, lmm_drug, corr_thres=cor_thres, norder=norder)
        graph.write_pdf('reports/lmm_association_ppi_{}.pdf'.format(name))
