from yw.ddpg_main.param.rl_fetch_pick_and_place_single_goal import params_config as base_params

params_config = base_params.copy()
params_config["config"] = ("RL_with_Dense_Rwd",)
params_config["env_name"] = "FetchPickAndPlaceDense-v1"
params_config["seed"] = 0
