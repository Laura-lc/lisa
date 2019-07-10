# SPDX-License-Identifier: Apache-2.0
#
# Copyright (C) 2019, Arm Limited and contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import functools
import operator
import math

import numpy as np
import pandas as pd
import scipy.integrate
import scipy.signal

def df_squash(df, start, end, column='delta'):
    """
    Slice a dataframe of deltas in [start:end] and ensure we have
    an event at exactly those boundaries.

    The input dataframe is expected to have a "column" which reports
    the time delta between consecutive rows, as for example dataframes
    generated by add_events_deltas().

    The returned dataframe is granted to have an initial and final
    event at the specified "start" ("end") index values, which values
    are the same of the last event before (first event after) the
    specified "start" ("end") time.

    Examples:

    Slice a dataframe to [start:end], and work on the time data so that it
    makes sense within the interval.

    Examples to make it clearer:

    df is:
    Time len state
    15    1   1
    16    1   0
    17    1   1
    18    1   0
    -------------

    df_squash(df, 16.5, 17.5) =>

    Time len state
    16.5  .5   0
    17    .5   1

    df_squash(df, 16.2, 16.8) =>

    Time len state
    16.2  .6   0

    :returns: a new df that fits the above description
    """
    if df.empty:
        return df

    end = min(end, df.index[-1] + df[column].values[-1])
    res_df = pd.DataFrame(data=[], columns=df.columns)

    if start > end:
        return res_df

    # There's a few things to keep in mind here, and it gets confusing
    # even for the people who wrote the code. Let's write it down.
    #
    # It's assumed that the data is continuous, i.e. for any row 'r' within
    # the trace interval, we will find a new row at (r.index + r.len)
    # For us this means we'll never end up with an empty dataframe
    # (if we started with a non empty one)
    #
    # What's we're manipulating looks like this:
    # (| = events; [ & ] = start,end slice)
    #
    # |   [   |   ]   |
    # e0  s0  e1  s1  e2
    #
    # We need to push e0 within the interval, and then tweak its duration
    # (len column). The mathemagical incantation for that is:
    # e0.len = min(e1.index - s0, s1 - s0)
    #
    # This takes care of the case where s1 isn't in the interval
    # If s1 is in the interval, we just need to cap its len to
    # s1 - e1.index

    prev_df = df[:start]
    middle_df = df[start:end]

    # Tweak the closest previous event to include it in the slice
    if not prev_df.empty and not (start in middle_df.index):
        res_df = res_df.append(prev_df.tail(1))
        res_df.index = [start]
        e1 = end

        if not middle_df.empty:
            e1 = middle_df.index[0]

        res_df[column] = min(e1 - start, end - start)

    if not middle_df.empty:
        res_df = res_df.append(middle_df)
        if end in res_df.index:
            # e_last and s1 collide, ditch e_last
            res_df = res_df.drop([end])
        else:
            # Fix the delta for the last row
            delta = min(end - res_df.index[-1], res_df[column].values[-1])
            res_df.at[res_df.index[-1], column] = delta

    return res_df

def df_merge(df_list, drop_columns=None, drop_inplace=False, filter_columns=None):
    """
    Merge a list of :class:`pandas.DataFrame`, keeping the index sorted.

    :param drop_columns: List of columns to drop prior to merging. This avoids
        ending up with extra renamed columns if some dataframes have column
        names in common.
    :type drop_columns: list(str)

    :param drop_inplace: Drop columns in the original dataframes instead of
        creating copies.
    :type drop_inplace: bool

    :param filter_columns: Dict of `{"column": value)` used to filter each
        dataframe prior to dropping columns. The columns are then dropped as
        they have a constant value.
    :type filter_columns: dict(str, object)
    """

    drop_columns = drop_columns if drop_columns else []

    if filter_columns:
        def filter_df(df):
            key = functools.reduce(
                operator.and_,
                (
                    df[col] == val
                    for col, val in filter_columns.items()
                )
            )
            return df[key]

        df_list = [
            filter_df(df)
            for df in df_list
        ]

        # remove the column to avoid duplicated useless columns
        drop_columns.extend(filter_columns.keys())
        # Since we just created dataframe slices, drop_inplace would give a
        # warning from pandas
        drop_inplace = False

    if drop_columns:
        def drop(df):
            filtered_df = df.drop(columns=drop_columns, inplace=drop_inplace)
            # when inplace=True, df.drop() returns None
            return df if drop_inplace else filtered_df

        df_list = [
            drop(df)
            for df in df_list
        ]

    def merge(df1, df2):
        return pd.merge(df1, df2, left_index=True, right_index=True, how='outer')

    return functools.reduce(merge, df_list)


def _resolve_x(y, x):
    """
    Resolve the `x` series to use for derivative and integral operations
    """

    if x is None:
        x = pd.Series(y.index)
        x.index = y.index
    return x


def series_derivate(y, x=None, order=1):
    """
    Compute a derivative of a :class:`pandas.Series` with respect to another
    series.

    :return: A series of `dy/dx`, where `x` is either the index of `y` or
        another series.

    :param y: Series with the data to derivate.
    :type y: pandas.DataFrame

    :param x: Series with the `x` data. If ``None``, the index of `y` will be
        used. Note that `y` and `x` are expected to have the same index.
    :type y: pandas.DataFrame or None

    :param order: Order of the derivative (1 is speed, 2 is acceleration etc).
    :type order: int
    """
    x = _resolve_x(y, x)

    for i in range(order):
        y = y.diff() / x.diff()

    return y


def series_integrate(y, x=None, sign=None, method='rect', rect_step='post'):
    """
    Compute the integral of `y` with respect to `x`.

    :return: A scalar :math:`\int_{x=A}^{x=B} y \, dx`, where `x` is either the
        index of `y` or another series.

    :param y: Series with the data to integrate.
    :type y: pandas.DataFrame

    :param x: Series with the `x` data. If ``None``, the index of `y` will be
        used. Note that `y` and `x` are expected to have the same index.
    :type y: pandas.DataFrame or None

    :param sign: Clip the data for the area in positive
        or negative regions. Can be any of:

        - ``+``: ignore negative data
        - ``-``: ignore positive data
        - ``None``: use all data

    :type sign: str or None

    :param method: The method for area calculation. This can
        be any of the integration methods supported in :mod:`numpy`
        or `rect`
    :type param: str

    :param rect_step: The step behaviour for `rect` method
    :type rect_step: str

    *Rectangular Method*

        - Step: Post

            Consider the following time series data

            .. code::

                2            *----*----*----+
                             |              |
                1            |              *----*----+
                             |
                0  *----*----+
                   0    1    2    3    4    5    6    7

            .. code::

                import pandas as pd
                a = [0, 0, 2, 2, 2, 1, 1]
                s = pd.Series(a)

            The area under the curve is:

            .. math::

                \sum_{k=0}^{N-1} (x_{k+1} - {x_k}) \\times f(x_k) \\\\
                (2 \\times 3) + (1 \\times 2) = 8

        - Step: Pre

            .. code::

                2       +----*----*----*
                        |              |
                1       |              +----*----*----+
                        |
                0  *----*
                   0    1    2    3    4    5    6    7

            .. code::

                import pandas as pd
                a = [0, 0, 2, 2, 2, 1, 1]
                s = pd.Series(a)

            The area under the curve is:

            .. math::

                \sum_{k=1}^{N} (x_k - x_{k-1}) \\times f(x_k) \\\\
                (2 \\times 3) + (1 \\times 3) = 9
    """

    x = _resolve_x(y, x)

    if sign == "+":
        y = y.clip(lower=0)
    elif sign == "-":
        y = y.clip(upper=0)
    elif sign is None:
        pass
    else:
        raise ValueError('Unsupported "sign": {}'.format(sign))

    if method == "rect":
        dx = x.diff()

        if rect_step == "post":
            dx = dx.shift(-1)

        return (y * dx).sum()


    # Make a DataFrame to make sure all rows stay aligned when we drop NaN,
    # which is needed by all the below methods
    df = pd.DataFrame({'x': x, 'y': y}).dropna()
    x = df['x']
    y = df['y']

    if method == 'trapz':
        return np.trapz(y, x)

    elif method == 'simps':
        return scipy.integrate.simps(y, x)

    else:
        raise ValueError('Unsupported integration method: {}'.format(method))


def series_mean(y, x=None, **kwargs):
    r"""
    Compute the average of `y` by integrating with respect to `x` and dividing
    by the range of `x`.

    :return: A scalar :math:`\int_{x=A}^{x=B} \frac{y}{| B - A |} \, dx`,
        where `x` is either the index of `y` or another series.

    :param y: Series with the data to integrate.
    :type y: pandas.DataFrame

    :param x: Series with the `x` data. If ``None``, the index of `y` will be
        used. Note that `y` and `x` are expected to have the same index.
    :type y: pandas.DataFrame or None

    :keyword arguments: Passed to :func:`series_integrate`.
    """
    x = _resolve_x(y, x)
    integral = series_integrate(y, x, **kwargs)

    return integral / (x.max() - x.min())


def series_window(series, window, method='inclusive'):
    """
    Select a portion of a :class:`pandas.Series`

    :param series: series to slice
    :type series: :class:`pandas.Series`

    :param window: two-tuple of index values for the start and end of the
        region to select.
    :type window: tuple(object)

    :param end: value of index at the end of the cropped series.
    :type end: object

    :param method: Choose how edges are handled:

        * `inclusive`: corresponds to default pandas float slicing behaviour.
        * `exclusive`: When no exact match is found, only index values within
            the range are selected
        * `nearest`: When no exact match is found, take the nearest index value.

    .. note:: The index of `series` must be monotonic and without duplicates.
    """

    if method == 'inclusive':
        # Default slicing behaviour of pandas' Float64Index is to be inclusive,
        # so we can use that knowledge to enable a fast path for common needs.
        if isinstance(series.index, pd.Float64Index):
            return series[slice(*window)]

        method = ('ffill', 'bfill')

    elif method == 'exclusive':
        method = ('bfill', 'ffill')

    elif method == 'nearest':
        method = ('nearest', 'nearest')

    else:
        raise ValueError('Slicing method not supported: {}'.format(method))

    index = series.index
    window = [
        index.get_loc(x, method=method)
        for x, method in zip(window, method)
    ]

    return series.iloc[slice(*window)]


def series_align_signal(ref, to_align, max_shift=None):
    """
    Align a signal to an expected reference signal using their
    cross-correlation.

    :returns: `(ref, to_align)` tuple, with `to_align` shifted by an amount
        computed to align as well as possible with `ref`. Both `ref` and
        `to_align` are resampled to have a fixed sample rate.

    :param ref: reference signal.
    :type ref: pandas.Series

    :param to_align: signal to align
    :type to_align: pandas.Series

    :param max_shift: Maximum shift allowed to align signals, in index units.
    :type max_shift: object or None
    """
    if ref.isnull().any() or to_align.isnull().any():
        raise ValueError('NaN needs to be dropped prior to alignment')

    # Select the overlapping part of the signals
    start = max(ref.index.min(), to_align.index.min())
    end = min(ref.index.max(), to_align.index.max())

    # Resample so that we operate on a fixed sampled rate signal, which is
    # necessary in order to be able to do a meaningful interpretation of
    # correlation argmax
    get_period = lambda series: pd.Series(series.index).diff().min()
    period = min(get_period(ref), get_period(to_align))
    num = math.ceil((end - start)/period)
    new_index = pd.Float64Index(np.linspace(start, end, num))

    to_align = to_align.reindex(new_index, method='ffill')
    ref = ref.reindex(new_index, method='ffill')

    # Compute the correlation between the two signals
    correlation = scipy.signal.signaltools.correlate(to_align, ref)
    # The most likely shift is the index at which the correlation is
    # maximum. correlation.argmax() can vary from 0 to 2*len(to_align), so we
    # re-center it.
    shift = correlation.argmax() - (len(to_align) - 1)

    # Cap the shift value
    if max_shift is not None:
        assert max_shift >= 0

        # Turn max_shift into a number of samples in the resampled signal
        max_shift = int(max_shift / period)

        # Adjust the sign of max_shift to match shift
        max_shift *= -1 if shift < 0 else 1

        if abs(shift) > abs(max_shift):
            shift = max_shift

    # Compensate the shift
    return ref, to_align.shift(-shift)


# vim :set tabstop=4 shiftwidth=4 textwidth=80 expandtab