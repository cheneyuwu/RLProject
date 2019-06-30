""" Active learning project

    This python script loads a trained rl policy and uses it to navigate the agent in its environment. You only need to
    provide the policy file generated by train*.py and the script will figure out which env should be used.

"""
import os
import pickle

import numpy as np
import tensorflow as tf

try:
    from mpi4py import MPI
except ImportError:
    MPI = None

from yw.util.util import set_global_seeds
from yw.ddpg_main import config


# DDPG Package import
from yw.tool import logger


def main(policy_file, seed, num_itr, render, env_args, **kwargs):


    rank = MPI.COMM_WORLD.Get_rank() if MPI != None else 0    
    
    # Seed everything
    set_global_seeds(seed)

    # Reset default graph every time this function is called.
    tf.reset_default_graph()
    tf.InteractiveSession()

    # Load policy.
    with open(policy_file, "rb") as f:
        policy = pickle.load(f)

    # Prepare params.
    params = {}
    params["env_name"] = policy.info["env_name"]
    params["r_scale"] = policy.info["r_scale"]
    params["r_shift"] = policy.info["r_shift"]
    params["eps_length"] = policy.info["eps_length"] if policy.info["eps_length"] != 0 else policy.T
    params["env_args"] = dict(env_args) if env_args != None else policy.info["env_args"]
    params["rank_seed"] = seed
    params["render"] = render
    params["rollout_batch_size"] = 1
    params = config.add_env_params(params=params)
    demo = config.config_demo(params=params, policy=policy)

    # Run evaluation.
    demo.clear_history()
    for _ in range(num_itr):
        demo.generate_rollouts()

    # record logs
    for key, val in demo.logs("test"):
        logger.record_tabular(key, np.mean(val))
    if rank == 0:
        logger.dump_tabular()


import sys
from yw.util.cmd_util import ArgParser

ap = ArgParser()

ap.parser.add_argument("--policy_file", help="demonstration training dataset", type=str, default=None)
ap.parser.add_argument("--seed", help="RNG seed", type=int, default=413)
ap.parser.add_argument("--num_itr", help="number of iterations", type=int, default=1)
ap.parser.add_argument("--render", help="render or not", type=int, default=1)
ap.parser.add_argument(
    "--env_arg",
    help="extra args passed to the environment",
    action="append",
    type=lambda kv: [kv.split(":")[0], eval(str(kv.split(":")[1] + '("' + kv.split(":")[2] + '")'))],
    dest="env_args",
)


if __name__ == "__main__":
    ap.parse(sys.argv)

    main(**ap.get_dict())
