#    Copyright 2015-2016 ARM Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""This module contains the class for plotting and
customizing Line/Linear Plots with :mod:`trappy.trace.FTrace`
This plot only works when run from an IPython notebook
"""

import matplotlib.pyplot as plt
from trappy.plotter import AttrConf
from trappy.plotter import Utils
from trappy.plotter.Constraint import ConstraintManager
from trappy.plotter.ILinePlotGen import ILinePlotGen
from trappy.plotter.AbstractDataPlotter import AbstractDataPlotter
from trappy.plotter.ColorMap import ColorMap
from trappy.plotter import IPythonConf
import pandas as pd

if not IPythonConf.check_ipython():
    raise ImportError("Ipython Environment not Found")

class ILinePlot(AbstractDataPlotter):
    """
    This class uses :mod:`trappy.plotter.Constraint.Constraint` to
    represent different permutations of input parameters. These
    constraints are generated by creating an instance of
    :mod:`trappy.plotter.Constraint.ConstraintManager`.

    :param trace: The input data
    :type trace: :mod:`trappy.trace.FTrace` or :mod:`pandas.DataFrame`, list or single

    :param column: specifies the name of the column to
           be plotted.
    :type column: (str, list(str))

    :param templates: TRAPpy events

        .. note::

                This is not required if a :mod:`pandas.DataFrame` is
                used

    :type templates: :mod:`trappy.base.Base`

    :param filters: Filter the column to be plotted as per the
        specified criteria. For Example:
        ::

            filters =
                    {
                        "pid": [ 3338 ],
                        "cpu": [0, 2, 4],
                    }
    :type filters: dict

    :param per_line: Used to control the number of graphs
        in each graph subplot row
    :type per_line: int

    :param concat: Draw all the pivots on a single graph
    :type concat: bool

    :param permute: Draw one plot for each of the traces specified
    :type permute: bool

    :param fill: Fill the area under the plots
    :type fill: bool

    :param drawstyle: Set the drawstyle to a matplotlib compatible
        drawing style.

        .. note::

            Only "steps-post" is supported as a valid value for
            the drawstyle. This creates a step plot.

    :type drawstyle: str

    :param signals: A string of the type event_name:column
        to indicate the value that needs to be plotted

        .. note::

            - Only one of `signals` or both `templates` and
              `columns` should be specified
            - Signals format won't work for :mod:`pandas.DataFrame`
              input

    :type signals: str

    :param legend_ncol: A positive integer that represents the
        number of columns in the legend
    :type legend_ncol: int
    """

    def __init__(self, traces, templates=None, **kwargs):
        # Default keys, each can be overridden in kwargs
        self._layout = None
        super(ILinePlot, self).__init__(traces=traces,
                                        templates=templates)

        self.set_defaults()

        for key in kwargs:
            self._attr[key] = kwargs[key]

        if "signals" in self._attr:
            self._describe_signals()

        self._check_data()

        if "column" not in self._attr:
            raise RuntimeError("Value Column not specified")

        if self._attr["drawstyle"] and self._attr["drawstyle"].startswith("steps"):
            self._attr["step_plot"] = True

        zip_constraints = not self._attr["permute"]

        self.c_mgr = ConstraintManager(traces, self._attr["column"], self.templates,
                                       self._attr["pivot"],
                                       self._attr["filters"], zip_constraints)


    def savefig(self, *args, **kwargs):
        raise NotImplementedError("Not Available for ILinePlot")

    def view(self, test=False):
        """Displays the graph"""

        # Defer installation of IPython components
        # to the .view call to avoid any errors at
        # when importing the module. This facilitates
        # the importing of the module from outside
        # an IPython notebook
        IPythonConf.iplot_install("ILinePlot")

        if self._attr["concat"]:
            self._plot_concat()
        else:
            self._plot(self._attr["permute"])

    def set_defaults(self):
        """Sets the default attrs"""
        self._attr["per_line"] = AttrConf.PER_LINE
        self._attr["concat"] = AttrConf.CONCAT
        self._attr["filters"] = {}
        self._attr["pivot"] = AttrConf.PIVOT
        self._attr["permute"] = False
        self._attr["drawstyle"] = None
        self._attr["step_plot"] = False
        self._attr["fill"] = AttrConf.FILL
        self._attr["draw_line"] = True
        self._attr["scatter"] = AttrConf.PLOT_SCATTER
        self._attr["point_size"] = AttrConf.POINT_SIZE
        self._attr["map_label"] = {}
        self._attr["legend_ncol"] = AttrConf.LEGEND_NCOL

    def _plot(self, permute):
        """Internal Method called to draw the plot"""
        pivot_vals, len_pivots = self.c_mgr.generate_pivots(permute)

        self._layout = ILinePlotGen(len_pivots, **self._attr)
        plot_index = 0
        for p_val in pivot_vals:
            data_frame = pd.Series()
            for constraint in self.c_mgr:

                if permute:
                    trace_idx, pivot = p_val
                    if constraint.trace_index != trace_idx:
                        continue
                    title = constraint.get_data_name() + ":"
                    legend = constraint._column
                else:
                    pivot = p_val
                    title = ""
                    legend = str(constraint)

                result = constraint.result
                if pivot in result:
                    data_frame[legend] = result[pivot]

            if pivot == AttrConf.PIVOT_VAL:
                title += ",".join(self._attr["column"])
            else:
                title += "{0}: {1}".format(self._attr["pivot"], self._attr["map_label"].get(pivot, pivot))

            self._layout.add_plot(plot_index, data_frame, title)
            plot_index += 1

        self._layout.finish()

    def _plot_concat(self):
        """Plot all lines on a single figure"""

        pivot_vals, _ = self.c_mgr.generate_pivots()
        plot_index = 0

        self._layout = ILinePlotGen(len(self.c_mgr), **self._attr)

        for constraint in self.c_mgr:
            result = constraint.result
            title = str(constraint)
            data_frame = pd.Series()

            for pivot in pivot_vals:
                if pivot in result:
                    if pivot == AttrConf.PIVOT_VAL:
                        key = ",".join(self._attr["column"])
                    else:
                        key = "{0}: {1}".format(self._attr["pivot"], self._attr["map_label"].get(pivot, pivot))

                    data_frame[key] = result[pivot]

            self._layout.add_plot(plot_index, data_frame, title)
            plot_index += 1

        self._layout.finish()
