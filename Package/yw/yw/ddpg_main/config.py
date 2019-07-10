import tensorflow as tf
import numpy as np

from yw.tool import logger

from yw.ddpg_main.ddpg import DDPG
from yw.ddpg_main.rollout import RolloutWorker

from yw.env.env_manager import EnvManager


DEFAULT_PARAMS = {
    # Config Summary
    "config": "default",
    "seed": 0,
    # Environment Config
    "env_name": "FetchPickAndPlace-v1",
    "r_scale": 1.0,  # re-scale the reward. Only use this for dense rewards.
    "r_shift": 0.0,  # re-scale the reward. Only use this for dense rewards.
    "eps_length": 0,  # change the length of the episode.
    "env_args": {},  # extra arguments passed to the environment.
    # DDPG Config
    "ddpg": {
        "buffer_size": int(1e6),
        "scope": "ddpg",
        "use_td3": 1,  # whether or not to use td3
        "layers": 3,  # number of layers in the critic/actor networks
        "hidden": 256,  # number of neurons in each hidden layers
        "Q_lr": 0.001,  # critic learning rate
        "pi_lr": 0.001,  # actor learning rate
        "action_l2": 1.0,  # quadratic penalty on actions (before rescaling by max_u)
        "batch_size": 256,  # per mpi thread, measured in transitions and reduced to even multiple of chunk_length.
        "batch_size_demo": 128,  # number of samples to be used from the demonstrations buffer, per mpi thread 128/1024 or 32/256
        "demo_critic": "none",  # whether or not to use shaping
        "demo_actor": "none",  # whether or not to use bc
        "q_filter": 1,  # whether or not a Q value filter should be used on the actor outputs
        "num_demo": 1000,  # number of expert demo episodes
        "prm_loss_weight": 0.001,  # weight corresponding to the primary loss
        "aux_loss_weight": 0.0078,  # weight corresponding to the auxilliary loss also called the cloning loss
        # double q learning
        "polyak": 0.95,  # polyak averaging coefficient for double q learning
        # normalization
        "norm_eps": 0.01,  # epsilon used for observation normalization
        "norm_clip": 5,  # normalized observations are cropped to this values
        # i/o clippings
        "clip_obs": 200.0,
        "clip_pos_returns": False,  # Whether or not this environment has positive return or not.
        "clip_return": False,
        # replay strategy to be used
        "replay_strategy": "none",  # supported modes: future, none for uniform
        "demo_replay_strategy": "none",  # supported modes: future, none for uniform
    },
    # HER Config
    "her": {"k": 4},  # number of additional goals used for replay
    # Rollouts Config
    "rollout": {
        "rollout_batch_size": 4,  # per mpi thread
        "random_eps": 0.3,  # percentage of time a random action is taken
        "noise_eps": 0.2,  # std of gaussian noise added to not-completely-random actions as a percentage of max_u
    },
    "evaluator": {
        "rollout_batch_size": 20,  # number of test rollouts per epoch, each consists of rollout_batch_size rollouts
        "random_eps": 0.0,
        "noise_eps": 0.01,
        "use_target_net": False,  # run test episodes with the target network
        "compute_Q": True,
    },
    # Training Config
    "train_rl_epochs": 1,
    "n_cycles": 10,  # per epoch
    "n_batches": 40,  # training batches per cycle
}


def log_params(params):
    for key in sorted(params.keys()):
        logger.info("{:<30}{}".format(key, params[key]))


# Helper Functions for Configuration
# =====================================


class EnvCache:
    """Only creates a new environment from the provided function if one has not yet already been
    created.

    This is useful here because we need to infer certain properties of the env, e.g.
    its observation and action spaces, without any intend of actually using it.

    """

    cached_envs = {}

    @staticmethod
    def get_env(make_env):
        if make_env not in EnvCache.cached_envs.keys():
            EnvCache.cached_envs[make_env] = make_env()
        return EnvCache.cached_envs[make_env]


def add_env_params(params):
    env_manager = EnvManager(
        env_name=params["env_name"],
        env_args=params["env_args"],
        r_scale=params["r_scale"],
        r_shift=params["r_shift"],
        eps_length=params["eps_length"],
    )
    logger.info(
        "Using environment %s with r scale down by %f shift by %f and max episode %f"
        % (params["env_name"], params["r_scale"], params["r_shift"], params["eps_length"])
    )
    params["make_env"] = env_manager.get_env
    tmp_env = EnvCache.get_env(params["make_env"])
    assert hasattr(tmp_env, "_max_episode_steps")
    params["T"] = tmp_env._max_episode_steps
    params["gamma"] = 1.0 - 1.0 / params["T"]
    assert hasattr(tmp_env, "max_u")
    params["max_u"] = np.array(tmp_env.max_u) if isinstance(tmp_env.max_u, list) else tmp_env.max_u
    # get environment dimensions
    tmp_env.reset()
    obs, _, _, info = tmp_env.step(tmp_env.action_space.sample())
    dims = {
        "o": obs["observation"].shape[0],  # the state
        "u": tmp_env.action_space.shape[0],
        "g": obs["desired_goal"].shape[0],  # extra state that does not change within 1 episode
    }
    for key, value in info.items():
        value = np.array(value)
        if value.ndim == 0:
            value = value.reshape(1)
        dims["info_{}".format(key)] = value.shape[0]
    params["dims"] = dims
    return params


def extract_params(params, prefix=""):
    extracted_params = {key.replace(prefix, ""): params[key] for key in params.keys() if key.startswith(prefix)}
    for key in extracted_params.keys():
        params["_" + key] = params[prefix + key]
        del params[prefix + key]
    return extracted_params


def configure_her(params):
    env = EnvCache.get_env(params["make_env"])
    env.reset()

    def reward_fun(ag_2, g_2, info):  # vectorized
        return env.compute_reward(achieved_goal=ag_2, desired_goal=g_2, info=info)

    # Prepare configuration for HER.
    her_params = params["her"]
    her_params["reward_fun"] = reward_fun

    logger.info("*** her_params ***")
    log_params(her_params)
    logger.info("*** her_params ***")

    return her_params


def configure_ddpg(params):
    # Extract relevant parameters.
    ddpg_params = params["ddpg"]

    if ddpg_params["replay_strategy"] == "her":
        rl_sample_params = configure_her(params)
    else:
        rl_sample_params = {}
    ddpg_params["replay_strategy"] = {"strategy": ddpg_params["replay_strategy"], "args": rl_sample_params}

    ddpg_params["demo_replay_strategy"] = {"strategy": ddpg_params["demo_replay_strategy"], "args": {}}

    # Update parameters
    ddpg_params.update(
        {
            "max_u": params["max_u"],
            "input_dims": params["dims"].copy(),  # agent takes an input observations
            "T": params["T"],
            "clip_return": (1.0 / (1.0 - params["gamma"])) if params["ddpg"]["clip_return"] else np.inf,
            "gamma": params["gamma"],
        }
    )
    ddpg_params["info"] = {
        "env_name": params["env_name"],
        "r_scale": params["r_scale"],
        "r_shift": params["r_shift"],
        "eps_length": params["eps_length"],
        "env_args": params["env_args"],
    }

    logger.info("*** ddpg_params ***")
    log_params(ddpg_params)
    logger.info("*** ddpg_params ***")

    policy = DDPG(**ddpg_params)
    return policy


def config_rollout(params, policy):
    rollout_params = params["rollout"]
    rollout_params.update({"dims": params["dims"], "T": params["T"]})

    logger.info("\n*** rollout_params ***")
    log_params(rollout_params)
    logger.info("*** rollout_params ***")

    rollout_worker = RolloutWorker(params["make_env"], policy, **rollout_params)
    rollout_worker.seed(params["seed"])

    return rollout_worker


def config_evaluator(params, policy):

    eval_params = params["evaluator"]

    eval_params.update({"dims": params["dims"], "T": params["T"]})

    logger.info("*** eval_params ***")
    log_params(eval_params)
    logger.info("*** eval_params ***")

    evaluator = RolloutWorker(params["make_env"], policy, **eval_params)
    evaluator.seed(params["seed"])

    return evaluator


def config_demo(params, policy):
    demo_params = {
        "compute_Q": True,
        "random_eps": 0.0,
        "noise_eps": 0.01,
        "render": params["render"],
        "T": params["eps_length"],
        "rollout_batch_size": params["rollout_batch_size"],
        "dims": params["dims"],
    }

    logger.info("*** demo_params ***")
    log_params(demo_params)
    logger.info("*** demo_params ***")

    demo = RolloutWorker(params["make_env"], policy, **demo_params)
    demo.seed(params["seed"])

    return demo
