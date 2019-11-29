import os
import pickle
import sys

import numpy as np
import tensorflow as tf

from td3fd import config
from td3fd import logger
from td3fd.util.util import set_global_seeds

try:
    from mpi4py import MPI
except ImportError:
    MPI = None


DEFAULT_PARAMS = {
    "seed": 0,
    "num_eps": 1,
    "fix_T": False,
    "demo": {"random_eps": 0.0, "noise_eps": 0.1, "compute_Q": True, "render": True, "num_episodes": 1},
}


def main(policy_file, **kwargs):
    assert policy_file is not None, "must provide the policy_file"

    # Setup
    logger.configure()
    assert logger.get_dir() is not None
    rank = MPI.COMM_WORLD.Get_rank() if MPI != None else 0

    params = DEFAULT_PARAMS.copy()
    # Seed everything
    set_global_seeds(params["seed"])
    tf.InteractiveSession()

    # Load policy.
    with open(policy_file, "rb") as f:
        policy = pickle.load(f)

    # Extract environment construction information
    env_name = policy.info["env_name"].replace("Dense", "")  # the reward should be sparse
    T = policy.info["eps_length"] if policy.info["eps_length"] != 0 else policy.T

    # Prepare params.
    params["env_name"] = env_name
    params["r_scale"] = policy.info["r_scale"]
    params["r_shift"] = policy.info["r_shift"]
    params["eps_length"] = T
    if "env_args" not in params.keys():
        params["env_args"] = policy.info["env_args"]
    params = config.add_env_params(params=params)
    demo = config.config_demo(params=params, policy=policy)

    # Run evaluation.
    demo.clear_history()
    for _ in range(params["num_eps"]):
        demo.generate_rollouts()

    # Log
    for key, val in demo.logs("test"):
        logger.record_tabular(key, np.mean(val))
    if rank == 0:
        logger.dump_tabular()

    tf.compat.v1.get_default_session().close()


if __name__ == "__main__":

    from td3fd.util.cmd_util import ArgParser

    ap = ArgParser()
    ap.parser.add_argument("--policy_file", help="demonstration training dataset", type=str, default=None)
    ap.parse(sys.argv)

    main(**ap.get_dict())
