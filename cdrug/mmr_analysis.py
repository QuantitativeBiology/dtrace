#!/usr/bin/env python
# Copyright (C) 2018 Emanuel Goncalves

import cdrug
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.colors import ListedColormap

GENES_CRISPR = ['WRN']
GENES_METHY = ['MLH1']
GENES_MUTATION = ['POLE', 'MLH1', 'MLH3', 'MSH2', 'MSH3', 'MSH6', 'PMS2']

TISSUES = ['Colorectal Carcinoma', 'Ovarian Carcinoma']
TISSUES_PALETTE = {'Colorectal Carcinoma': '#f28100', 'Ovarian Carcinoma': '#28B8A4', 'Other': '#ECF0F1'}

MUTAION_PALETTE = {'Frameshift': '#e31a1c', 'Missense': '#1f78b4' , 'Nonsense': '#ffd92f', 'Other': '#ECF0F1', 'None': '#ECF0F1'}

def get_gene_mutation_class(wes, gene, samples):
    wes_gene = wes[wes['Gene'].isin([gene])]

    wes_gene = wes_gene.assign(
        Classification=wes_gene['Classification'].apply(lambda v: v.capitalize() if v.capitalize() in MUTAION_PALETTE else 'Other')
    )

    wes_gene = pd.pivot_table(
        wes_gene, index='SAMPLE', columns='Gene', values='Classification', aggfunc=set
    )

    wes_gene = wes_gene\
        .reindex(set(samples).intersection(wes['SAMPLE']))\
        .replace(np.nan, 'None')\
        .reindex(samples)

    wes_gene = wes_gene[gene].rename('{} (Mutation)'.format(gene))

    return wes_gene


if __name__ == '__main__':
    # - Import
    # Samplesheet
    ss = pd.read_csv(cdrug.SAMPLESHEET_FILE, index_col=0).dropna(subset=['Cancer Type'])

    # WES
    wes = pd.read_csv(cdrug.WES_COUNT)

    # Mutation load
    n_mutations = wes.groupby('SAMPLE')['Classification'].count().rename('mutations')

    # CRISPR gene-level corrected fold-changes
    crispr = pd.read_csv(cdrug.CRISPR_GENE_BAGEL, index_col=0, sep='\t').dropna()
    crispr_binary = pd.read_csv(cdrug.CRISPR_GENE_BINARY, sep='\t', index_col=0).dropna().astype(int)

    # Methylation
    methy = pd.read_csv(cdrug.METHYLATION_GENE_PROMOTER, index_col=0)

    # Samples
    samples = list(crispr)
    print('Samples: %d' % len(samples))

    # - Build plot data-frame
    # Initialise data-frame
    plot_df = pd.concat([
        n_mutations.reindex(samples),       # Add mutation burden
        ss.reindex(samples)['Microsatellite'].replace({'MSI-L': 'MSI-S'}),     # Add MSI status
        ss.reindex(samples)['Cancer Type'].apply(lambda v: v if str(v) == 'nan' or v in TISSUES else 'Other'),     # Add Cancer type
    ], axis=1).dropna()

    # Add CRISPR
    plot_df = pd.concat([
        plot_df,
        pd.DataFrame([crispr_binary.loc[g].reindex(samples).rename('{} (Essentiality)'.format(g)) for g in GENES_CRISPR]).T
    ], axis=1)

    # Add Methylation
    plot_df = pd.concat([
        plot_df,
        pd.DataFrame([methy.loc[g].reindex(samples).apply(lambda x: int(x > .66)).rename('{} (Hypermethylation)'.format(g)) for g in GENES_METHY]).T
    ], axis=1)

    # Add Mutation
    plot_df = pd.concat([
        plot_df,
        pd.DataFrame([get_gene_mutation_class(wes, g, samples) for g in GENES_MUTATION]).T
    ], axis=1)

    plot_df = plot_df.reset_index().sort_values('mutations', ascending=False)
    plot_df = plot_df.assign(pos=range(plot_df.shape[0]))

    plot_df = plot_df.dropna()

    # - Plot
    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, sharex=True, sharey=False, gridspec_kw={'height_ratios': [2, 2]})
    plt.subplots_adjust(wspace=.1, hspace=.1)

    # Upper part
    ax1.set_xlabel('')
    ax1.tick_params(axis='x', which='both', bottom='off', top='off', labelbottom='off')
    ax1.yaxis.grid(True, color=cdrug.BIPAL_DBGD[0], linestyle='-', linewidth=.1)
    ax1.set_yscale('log', basey=10)

    ax1.scatter(plot_df['pos'], plot_df['mutations'], color=cdrug.BIPAL_DBGD[0], edgecolor='white', lw=.1, s=7)
    ax1.set_ylabel('Number of mutations')

    ax1.set_adjustable('box-forced')
    ax1.set_xticks(np.arange(0, plot_df.shape[0], 20))

    # Lower part
    marker_style = dict(lw=0, mew=.1, marker='o', markersize=np.sqrt(7))

    pos, ylabels = 0, []

    for t, c in TISSUES_PALETTE.items():
        df = plot_df[plot_df['Cancer Type'] == t]
        ax2.plot(df['pos'], np.zeros(df.shape[0]) + pos, fillstyle='full', color=c, **marker_style, label=t)

    ylabels.append((pos, 'Cancer Type'))
    pos -= 2

    for l, fs in zip(*(['MSI-H', 'MSI-S'], ['full', 'none'])):
        df = plot_df.query("Microsatellite == '{}'".format(l))
        ax2.plot(df['pos'], np.zeros(df.shape[0]) + pos, fillstyle=fs, color=cdrug.BIPAL_DBGD[0], **marker_style)

    ylabels.append((pos, 'MSI status'))
    pos -= 2

    for glist, glabel in zip(*([GENES_CRISPR, GENES_METHY], ['Essentiality', 'Hypermethylation'])):
        for g in glist:
            for l, fs in zip(*([1, 0], ['full', 'none'])):
                df = plot_df[plot_df['{} ({})'.format(g, glabel)] == l]

                ax2.plot(df['pos'], np.zeros(df.shape[0]) + pos, fillstyle=fs, color=cdrug.BIPAL_DBGD[0], **marker_style, label=l)

            ylabels.append((pos, '{}'.format(g, glabel)))
            pos -= 1
        pos -= 1

    for g in GENES_MUTATION:
        for p, ms in plot_df[['pos', '{} (Mutation)'.format(g, glabel)]].values:
            if ms == 'None':
                fs, c, mfca, l = 'none', cdrug.BIPAL_DBGD[0], cdrug.BIPAL_DBGD[0], ms

            elif len(ms) == 1:
                fs, c, mfca, l = 'full', MUTAION_PALETTE[list(ms)[0]], MUTAION_PALETTE[list(ms)[0]], list(ms)[0]

            elif len(ms) == 2:
                fs, c, mfca, l = 'bottom', MUTAION_PALETTE[list(ms)[0]], MUTAION_PALETTE[list(ms)[1]], None

            ax2.plot(p, pos, fillstyle=fs, color=c, markerfacecoloralt=mfca, **marker_style, label=l)

        ylabels.append((pos, '{}'.format(g)))
        pos -= 1

    ax2.set_adjustable('box-forced')
    ax2.set_xlabel('Number of cell lines')
    ax2.set_yticks(list(zip(*ylabels))[0])
    ax2.set_yticklabels(list(zip(*ylabels))[1])
    ax2.set_xticks(np.arange(0, plot_df.shape[0], 20))

    # WRN essential vline
    df = plot_df[plot_df['WRN (Essentiality)'] == 1]

    for p in df['pos']:
        ax1.axvline(x=p, c=cdrug.BIPAL_DBGD[1], linewidth=.3, zorder=0, clip_on=False)
        ax2.axvline(x=p, c=cdrug.BIPAL_DBGD[1], linewidth=.3, zorder=0, clip_on=False)

    # Legend
    by_label = {l: p for p, l in zip(*(ax2.get_legend_handles_labels()))}
    by_label_order = ['Colorectal Carcinoma', 'Ovarian Carcinoma', 'Other', 'Frameshift', 'Missense', 'Nonsense', 'Other']
    ax2.legend([by_label[k] for k in by_label_order], by_label_order, bbox_to_anchor=(1.02, 0.9), prop={'size': 6})

    plt.gcf().set_size_inches(10, 4)
    plt.savefig('reports/mmr_mutation_count.png', bbox_inches='tight', dpi=600)
    plt.close('all')
