import os
os.environ['SDL_AUDIODRIVER'] = 'dsp'
os.environ['CUDA_VISIBLE_DEVICES'] = "-1"

from train_atari import AtariModel, get_env, make_env_creator
from pettingzooenv import PettingZooEnv
from ray.rllib.models import ModelCatalog
from ray.tune.registry import register_env, register_trainable
from ray import tune
import gym
import random
import numpy as np
import ray
from pettingzoo.utils.to_parallel import from_parallel
import os
import sys
import pickle

from ray.rllib.rollout import rollout, keep_going, DefaultMapping
from ray.rllib.agents.dqn import ApexTrainer

from supersuit import clip_reward_v0, sticky_actions_v0, resize_v0
from supersuit import frame_skip_v0, frame_stack_v1, agent_indicator_v0

if __name__ == "__main__":
    methods = ["ADQN", "PPO", "RDQN"]

    assert len(sys.argv) == 4, "Input the environment name, data_path, checkpoint_num"
    env_name = sys.argv[1].lower()
    data_path = sys.argv[2]
    checkpoint_num = sys.argv[3]
    method = "ADQN"
    assert method in methods, "Method should be one of {}".format(methods)

    checkpoint_path = f"{data_path}/checkpoint_{checkpoint_num}/checkpoint-{checkpoint_num}"

    Trainer = ApexTrainer

    game_env = get_env(env_name)

    def env_creator(args):
        env = game_env.env(obs_type='grayscale_image')
        #env = clip_reward_v0(env, lower_bound=-1, upper_bound=1)
        env = sticky_actions_v0(env, repeat_action_probability=0.25)
        env = resize_v0(env, 84, 84)
        #env = color_reduction_v0(env, mode='full')
        env = frame_skip_v0(env, 4)
        env = frame_stack_v1(env, 4)
        env = agent_indicator_v0(env, type_only=False)
        return env

    register_env(env_name, lambda config: PettingZooEnv(env_creator(config)))
    test_env = PettingZooEnv(env_creator({}))
    obs_space = test_env.observation_space
    act_space = test_env.action_space

    ModelCatalog.register_custom_model("AtariModel", AtariModel)

    def gen_policy(i):
        config = {
            "model": {
                "custom_model": "AtariModel",
            },
            "gamma": 0.99,
        }
        return (None, obs_space, act_space, config)
    policies = {"policy_0": gen_policy(0)}

    config_path = os.path.join(data_path, "params.pkl")
    with open(config_path, "rb") as f:
        config = pickle.load(f)

    config['num_gpus']=0
    config['num_workers']=1
    # # ray.init()

    results_path = os.path.join(data_path,"checkpoint_values")
    os.makedirs(results_path,exist_ok=True)
    result_path = os.path.join(results_path,f"checkpoint{checkpoint_num}.txt")

    ray.init(num_gpus=0,num_cpus=2)#num_cpus=0,num_gpus=0)

    RLAgent = Trainer(env=env_name, config=config)
    RLAgent.restore(checkpoint_path)

    max_num_steps = 20000
    env = (env_creator(0))
    total_rewards = dict(zip(env.agents, [[] for _ in range(env.num_agents)]))
    num_steps = 0
    while num_steps < max_num_steps:
        observation = env.reset()
        prev_actions = env.rewards
        prev_rewards = env.rewards
        rewards = dict(zip(env.agents, [[0] for _ in range(env.num_agents)]))
        done = False
        iteration = 0
        policy_agent = 'first_0'
        while not done and num_steps < max_num_steps:
            for _ in env.agents:
                #print(observation.shape)
                #imsave("./"+str(iteration)+".png",observation[:,:,0])
                #env.render()
                observation = env.observe(env.agent_selection)
                if env.agent_selection == policy_agent:
                   action, _, _ = RLAgent.get_policy("policy_0").compute_single_action(observation, prev_action=prev_actions[env.agent_selection], prev_reward=prev_rewards[env.agent_selection])
                else:
                   action = env.action_spaces[policy_agent].sample() #same action space for all agents
                # action, _, _ = RLAgent.get_policy("policy_0").compute_single_action(observation, prev_action=prev_actions[env.agent_selection], prev_reward=prev_rewards[env.agent_selection])

                #print('Agent: {}, action: {}'.format(env.agent_selection,action))
                prev_actions[env.agent_selection] = action
                env.step(action, observe=False)
                #print('reward: {}, done: {}'.format(env.rewards, env.dones))
            prev_rewards = env.rewards
            for agent in env.agents:
                rewards[agent].append(prev_rewards[agent])
            done = any(env.dones.values())
            iteration += 1
            num_steps += 1
        for agent in env.agents:
            total_rewards[agent].append(np.sum(rewards[agent]))
        for agent in env.agents:
            print("Agent: {}, Reward: {}".format(agent, np.mean(rewards[agent])))
        print('Total reward: {}'.format(total_rewards))

    out_stat_fname = result_path
    mean_rew = np.mean(total_rewards[policy_agent])
    open(out_stat_fname,'w').write(str(mean_rew))
