"""Testing batch functions in fmu-ensemble."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import time
import datetime

import yaml
import pandas as pd

from fmu.ensemble import etc
from fmu.ensemble import ScratchEnsemble, EnsembleSet
from fmu.ensemble.common import use_concurrent, set_concurrent

fmux = etc.Interaction()
logger = fmux.basiclogger(__name__, level="INFO")

if not fmux.testsetup():
    raise SystemExit()


def test_batch():
    """Test batch processing at time of object initialization"""
    if "__file__" in globals():
        # Easen up copying test code into interactive sessions
        testdir = os.path.dirname(os.path.abspath(__file__))
    else:
        testdir = os.path.abspath(".")

    ens = ScratchEnsemble(
        "reektest",
        testdir + "/data/testensemble-reek001/" + "realization-*/iter-0",
        batch=[
            {"load_scalar": {"localpath": "npv.txt"}},
            {"load_smry": {"column_keys": "FOPT", "time_index": "yearly"}},
            {"load_smry": {"column_keys": "*", "time_index": "daily"}},
        ],
    )
    assert len(ens.get_df("npv.txt")) == 5
    assert len(ens.get_df("unsmry--daily")["FOPR"]) == 5490
    assert len(ens.get_df("unsmry--yearly")["FOPT"]) == 25

    # Also possible to batch process afterwards:
    ens = ScratchEnsemble(
        "reektest", testdir + "/data/testensemble-reek001/" + "realization-*/iter-0"
    )
    ens.process_batch(
        batch=[
            {"load_scalar": {"localpath": "npv.txt"}},
            {"load_smry": {"column_keys": "FOPT", "time_index": "yearly"}},
            {"load_smry": {"column_keys": "*", "time_index": "daily"}},
        ]
    )
    assert len(ens.get_df("npv.txt")) == 5
    assert len(ens.get_df("unsmry--daily")["FOPR"]) == 5490
    assert len(ens.get_df("unsmry--yearly")["FOPT"]) == 25


def test_yaml():
    """Test loading batch commands from yaml files"""

    # This is subject to change

    yamlstr = """
scratch_ensembles:
  iter1: data/testensemble-reek001/realization-*/iter-0
batch:
  - load_scalar:
      localpath: npv.txt
  - load_smry:
      column_keys: FOPT
      time_index: yearly
  - load_smry:
      column_keys: "*"
      time_index: daily"""
    ymlconfig = yaml.safe_load(yamlstr)

    testdir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(testdir)
    ensset = EnsembleSet()

    for ensname, enspath in ymlconfig["scratch_ensembles"].items():
        ensset.add_ensemble(ScratchEnsemble(ensname, paths=enspath))
    ensset.process_batch(ymlconfig["batch"])

    assert "parameters.txt" in ensset.keys()
    assert "OK" in ensset.keys()
    assert "npv.txt" in ensset.keys()
    assert not ensset.get_df("unsmry--yearly").empty


def sleeper():
    """Sleeps for one second.

        This function must be a module member for it to be
        pickled in concurrent applications"""
    time.sleep(1)
    return pd.DataFrame()


def test_speedup():
    """Naive test of speedup in concurrent mode"""

    testdir = os.path.dirname(os.path.abspath(__file__))
    ens = ScratchEnsemble(
        "reektest", testdir + "/data/testensemble-reek001/" + "realization-*/iter-0"
    )

    set_concurrent(True)
    # really_concurrent = use_concurrent()
    start_time = datetime.datetime.now()
    ens.process_batch(batch=[{"apply": {"callback": sleeper}}])
    end_time = datetime.datetime.now()
    conc_elapsed = (end_time - start_time).total_seconds()
    print("FMU_CONCURRENCY: {}".format(use_concurrent()))
    print("Elapsed time for concurrent batch apply sleep: {}".format(conc_elapsed))

    set_concurrent(False)
    start_time = datetime.datetime.now()
    ens.process_batch(batch=[{"apply": {"callback": sleeper}}])
    end_time = datetime.datetime.now()
    seq_elapsed = (end_time - start_time).total_seconds()
    print("FMU_CONCURRENCY: {}".format(use_concurrent()))
    print("Elapsed time for sequential batch apply sleep: {}".format(seq_elapsed))

    if really_concurrent:
        assert seq_elapsed > conc_elapsed * 4
