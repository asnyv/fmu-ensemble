# -*- coding: utf-8 -*-
"""Implementation of realization classes

A realization is a set of results from one subsurface model
realization. A realization can be either defined from
its output files from the FMU run on the file system,
it can be computed from other realizations, or it can be
an archived realization.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import re
import glob
import pandas as pd

import ert.ecl
from fmu import config

fmux = config.etc.Interaction()
logger = fmux.basiclogger(__name__)

if not fmux.testsetup():
    raise SystemExit()


class ScratchRealization(object):
    r"""A representation of results still present on disk

    ScratchRealization's point to the filesystem for their
    contents.

    A realization must at least contain a STATUS file.
    Additionally, jobs.json and parameters.txt will be attempted
    loaded by default.

    The realization is defined by the pointers to the filesystem.
    When asked for, this object will return data from the
    filesystem (or from cache if already computed).

    The files dataframe is the central filesystem pointer
    repository for the object. It will at least contain
    the columns
    * FULLPATH absolute path to a file
    * FILETYPE filename extension (after last dot)
    * LOCALPATH relative filename inside realization diretory
    * BASENAME filename only. No path. Includes extension

    This dataframe is available as a read-only property from the object

    Args:
        path (str): absolute or relative path to a directory
            containing a realizations files.
        realidxregexp: a compiled regular expression which
            is used to determine the realization index (integer)
            from the path. First match is the index.
            Default: realization-(\d+)
    """
    def __init__(self, path,
                 realidxregexp=re.compile(r'.*realization-(\d+)')):
        self._origpath = path

        self.files = pd.DataFrame(columns=['FULLPATH', 'FILETYPE',
                                           'LOCALPATH', 'BASENAME'])
        self._eclsum = None  # Placeholder for caching

        abspath = os.path.abspath(path)
        realidxmatch = re.match(realidxregexp, abspath)
        if realidxmatch:
            self.index = int(realidxmatch.group(1))
        else:
            logger.warn('Realization %s not valid, skipping',
                        abspath)
            raise ValueError

        # Now look for a minimal subset of files
        if os.path.exists(os.path.join(abspath, 'STATUS')):
            self.files = self.files.append({'LOCALPATH': 'STATUS',
                                            'FILETYPE': 'STATUS',
                                            'FULLPATH': os.path.join(abspath,
                                                                     'STATUS')},
                                           ignore_index=True)
        else:
            logger.warn("Invalid realization, no STATUS file, %s",
                        abspath)
            raise ValueError
        if os.path.exists(os.path.join(abspath, 'jobs.json')):
            self.files = self.files.append({'LOCALPATH': 'jobs.json',
                                            'FILETYPE': 'json',
                                            'FULLPATH': os.path.join(abspath,
                                                                     'jobs.json')},
                                           ignore_index=True)

        if os.path.exists(os.path.join(abspath, 'parameters.txt')):
            self.files = self.files.append({'LOCALPATH': 'parameters.txt',
                                            'FILETYPE': 'txt',
                                            'FULLPATH': os.path.join(abspath,
                                                                     'parameters.txt')},
                                           ignore_index=True)

    @property
    def parameters(self):
        """Getter for get_parameters(convert_numeric=True)
        """
        return self.get_parameters(self)

    def get_parameters(self, convert_numeric=True):
        """Return the contents of parameters.txt as a dict

        Strings will attempted to be parsed as numeric, and
        dictionary datatypes will be either int, float or string.

        Parsing is aggressive, parameter values that are by chance
        integers in a particular realization will be integers,
        but should aggregate well with floats from other realizations.

        Returns:
            dict: keys are the first column in parameters.txt, values from
                the second column
        """
        paramfile = self.files[self.files.LOCALPATH == 'parameters.txt']
        params = pd.read_table(paramfile.FULLPATH.values[0], sep=r'\s+',
                               index_col=0, dtype=str,
                               header=None)[1].to_dict()
        # pandas.read_table has its own numerics parsing, but this is turned
        # off by dtype=str above.
        if convert_numeric:
            for key in params:
                params[key] = parse_number(params[key])
        return params

    def get_eclsum(self):
        """
        Fetch the Eclipse Summary file from the realization
        and return as a libecl EclSum object

        Unless the UNSMRY file has been discovered, it will
        pick the file from the glob eclipse/model/*UNSMRY

        Warning: If you have multiple UNSMRY files and have not
        performed explicit discovery, this function will
        not help you (yet).

        Returns:
           EclSum: object representing the summary file
        """
        if self._eclsum:  # Return cached object if available
            return self._eclsum

        unsmry_file_row = self.files[self.files.FILETYPE == 'UNSMRY']
        unsmry_filename = None
        if len(unsmry_file_row) == 1:
            unsmry_filename = unsmry_file_row.FULLPATH.values[0]
        else:
            unsmry_fileguess = os.path.join(self._origpath, 'eclipse/model',
                                            '*.UNSMRY')
            unsmry_filename = glob.glob(unsmry_fileguess)[0]
        if not os.path.exists(unsmry_filename):
            return None
        # Cache result
        self._eclsum = ert.ecl.EclSum(unsmry_filename)
        return self._eclsum

    def get_smryvalues(self, props_wildcard=None):
        """
        Fetch selected vectors from Eclipse Summary data.

        Args:
            props_wildcard : string or list of strings with vector
                wildcards
        Returns:
            a dataframe with values. Raw times from UNSMRY.
            Empty dataframe if no summary file data available
        """
        if not self._eclsum:  # check if it is cached
            self.get_eclsum()

        if not self._eclsum:
            return pd.DataFrame()

        if not props_wildcard:
            props_wildcard = [None]
        if isinstance(props_wildcard, str):
            props_wildcard = [props_wildcard]
        props = set()
        for prop in props_wildcard:
            props = props.union(set(self._eclsum.keys(prop)))
        if 'numpy_vector' in dir(self._eclsum):
            data = {prop: self._eclsum.numpy_vector(prop, report_only=True) for
                    prop in props}
        else:  # get_values() is deprecated in newer libecl
            data = {prop: self._eclsum.get_values(prop, report_only=True) for
                    prop in props}
        dates = self._eclsum.get_dates(report_only=True)
        return pd.DataFrame(data=data, index=dates)


def parse_number(value):
    """Try to parse the string first as an integer, then as float,
    if both fails, return the original string.

    Caveats: Know your Python numbers:
    https://stackoverflow.com/questions/379906/how-do-i-parse-a-string-to-a-float-or-int-in-python

    Beware, this is a minefield.

    Returns:
        int, float or string
    """
    if isinstance(value, int):
        return value
    elif isinstance(value, float):
        if int(value) == value:
            return int(value)
        return value
    else:  # noqa
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value


class VirtualRealization():
    """A computed or archived realization.

    Computed or archived, one cannot assume to have access to the file
    system containing original data.

    Datatables that in a ScratchRealization was available through the
    files dataframe, is now available as dataframes in a dict accessed
    by the localpath in the files dataframe from ScratchRealization-

    """
    def __init__(self, path=None, description=None):
        self._description = ''
        if description:
            self._description = description
