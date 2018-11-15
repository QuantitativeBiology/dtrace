#!/usr/bin/env python
# Copyright (C) 2018 Emanuel Goncalves

import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.patches as mpatches
from scipy.stats import pearsonr
from crispy.qc_plot import QCplot


class MidpointNormalize(colors.Normalize):
    def __init__(self, vmin=None, vmax=None, midpoint=None, clip=False):
        self.midpoint = midpoint
        colors.Normalize.__init__(self, vmin, vmax, clip)

    def __call__(self, value, clip=None):
        x, y = [self.vmin, self.midpoint, self.vmax], [0, 0.5, 1]
        return np.ma.masked_array(np.interp(value, x, y))


class Plot(object):
    # - DEFAULT AESTHETICS
    SNS_RC = {
        'axes.linewidth': .3,
        'xtick.major.width': .3,
        'ytick.major.width': .3,
        'xtick.major.size': 2.5,
        'ytick.major.size': 2.5,
        'xtick.direction': 'in',
        'ytick.direction': 'in'
    }

    PAL_SET2 = sns.color_palette('Set2', n_colors=8).as_hex()

    PAL_DTRACE = [PAL_SET2[1], '#E1E1E1', '#656565']

    BOXPROPS = dict(linewidth=1.)
    WHISKERPROPS = dict(linewidth=1.)
    MEDIANPROPS = dict(linestyle='-', linewidth=1., color=PAL_DTRACE[0])
    FLIERPROPS = dict(
        marker='o', markerfacecolor='black', markersize=2., linestyle='none', markeredgecolor='none', alpha=.6
    )

    MARKERS = dict(Sanger='o', Broad='X')

    def __init__(self):
        sns.set(style='ticks', context='paper', rc=self.SNS_RC, font_scale=.75)

    def plot_corrplot(
            self, x, y, style, dataframe, add_hline=True, add_vline=True, annot_text=None, lowess=False
    ):
        grid = sns.JointGrid(x, y, data=dataframe, space=0)

        # Joint
        for t, df in dataframe.groupby(style):
            grid.ax_joint.scatter(
                x=df[x], y=df[y], edgecolor='w', lw=.1, s=5, color=self.PAL_DTRACE[2], marker=self.MARKERS[t], label=t,
                alpha=.8
            )

        grid.plot_joint(sns.regplot, data=dataframe, line_kws=dict(lw=1., color=self.PAL_DTRACE[0]), marker='', lowess=lowess)

        # Annotation
        if annot_text is None:
            cor, pval = pearsonr(dataframe[x], dataframe[y])
            annot_text = f'R={cor:.2g}, p={pval:.1e}'

        grid.ax_joint.text(.95, .05, annot_text, fontsize=5, transform=grid.ax_joint.transAxes, ha='right')

        # Marginals
        grid.plot_marginals(sns.distplot, kde=False, hist_kws=dict(linewidth=0), color=self.PAL_DTRACE[2])

        # Extra
        if add_hline:
            grid.ax_joint.axhline(0, ls='-', lw=0.1, c=self.PAL_DTRACE[1], zorder=0)

        if add_vline:
            grid.ax_joint.axvline(0, ls='-', lw=0.1, c=self.PAL_DTRACE[1], zorder=0)

        grid.ax_joint.legend(prop=dict(size=4), frameon=False, loc=2)

        return grid

    def plot_multiple(self, x, y, style, dataframe, order=None, ax=None):
        if ax is None:
            ax = plt.gca()

        if order is None:
            order = list(dataframe.groupby(y)[x].mean().sort_values(ascending=False).index)

        dataframe = dataframe.dropna(subset=[x, y, style])

        pal = pd.Series(QCplot.get_palette_continuous(len(order), self.PAL_DTRACE[2]), index=order)

        sns.boxplot(
            x=x, y=y, data=dataframe, orient='h', palette=pal.to_dict(), sym='', saturation=1., showcaps=False,
            order=order, ax=ax
        )

        for t, df in dataframe.groupby(style):
            sns.stripplot(
                x=x, y=y, data=df, orient='h', palette=pal.to_dict(), size=2, edgecolor='white',
                linewidth=.1, order=order, marker=self.MARKERS[t], label=t, jitter=.3, ax=ax
            )

        handles, labels = ax.get_legend_handles_labels()
        legend_by_label = dict(zip(list(reversed(labels)), list(reversed(handles))))

        ax.legend(legend_by_label.values(), legend_by_label.keys(), prop=dict(size=4), frameon=False, loc=4)

    @staticmethod
    def _marginal_boxplot(a, xs=None, ys=None, zs=None, vertical=False, **kws):
        if vertical:
            ax = sns.boxplot(x=zs, y=ys, orient='v', **kws)
        else:
            ax = sns.boxplot(x=xs, y=zs, orient='h', **kws)

        ax.set_ylabel('')
        ax.set_xlabel('')

    @classmethod
    def plot_corrplot_discrete(
            cls, x, y, z, plot_df, scatter_kws=None, line_kws=None, legend_title='', discrete_pal=None, hue_order=None
    ):
        # Defaults
        if scatter_kws is None:
            scatter_kws = dict(edgecolor='w', lw=.3, s=12)

        if line_kws is None:
            line_kws = dict(lw=1., color=cls.PAL_DTRACE[0])

        pal = {0: cls.PAL_DTRACE[2], 1: cls.PAL_DTRACE[0]}

        #
        g = sns.JointGrid(x, y, plot_df, space=0, ratio=8)

        g.plot_marginals(
            cls._marginal_boxplot, palette=pal if discrete_pal is None else discrete_pal, data=plot_df, linewidth=.3,
            fliersize=1, notch=False, saturation=1.0, xs=x, ys=y, zs=z
        )

        sns.regplot(
            x=x, y=y, data=plot_df, color=pal[0], truncate=True, fit_reg=True, scatter_kws=scatter_kws,
            line_kws=line_kws, ax=g.ax_joint
        )
        sns.regplot(
            x=x, y=y, data=plot_df[plot_df[z] == 1], color=pal[1], truncate=True, fit_reg=False,
            scatter_kws=scatter_kws, ax=g.ax_joint
        )

        g.annotate(pearsonr, template='R={val:.2g}, p={p:.1e}', loc=4, frameon=False)

        g.ax_joint.axhline(0, ls='-', lw=0.3, c=pal[0], alpha=.2)
        g.ax_joint.axvline(0, ls='-', lw=0.3, c=pal[0], alpha=.2)

        g.set_axis_labels('{} (log2 FC)'.format(x), '{} (ln IC50)'.format(y))

        if discrete_pal is None:
            handles = [mpatches.Circle([.0, .0], .25, facecolor=c, label='Yes' if t else 'No') for t, c in pal.items()]
        elif hue_order is None:
            handles = [mpatches.Circle([.0, .0], .25, facecolor=c, label=t) for t, c in discrete_pal.items()]
        else:
            handles = [mpatches.Circle([.0, .0], .25, facecolor=discrete_pal[t], label=t) for t in hue_order]

        g.ax_marg_y.legend(handles=handles, title=legend_title, loc='center left', bbox_to_anchor=(1, 0.5),
                           frameon=False)

        plt.suptitle(z, y=1.05, fontsize=8)

        return g
