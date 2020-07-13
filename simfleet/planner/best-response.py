import json
import random

from simfleet.planner.planner import Planner
from loguru import logger
from constants import SPEED, STARTING_FARE, PRICE_PER_kWh, PENALTY, PRICE_PER_KM


class BestResponse:

    def __init__(self):
        self.config_dic = None
        self.actions_dic = None
        self.routes_dic = None
        self.joint_plan = None
        self.agents = None

    def initialize(self):
        try:
            f2 = open("3_planner_config.json", "r")
            self.config_dic = json.load(f2)

            f2 = open("test-actions.json", "r")
            self.global_actions = json.load(f2)

            f2 = open("all-routes.json", "r")
            self.routes_dic = json.load(f2)

        except Exception as e:
            print(str(e))
            exit()

    def create_agents(self):
        agents = {}
        for agent in self.config_dic.get('transports'):
            agent_id = agent.get('name')
            agents[agent_id] = {
                'id': agent_id,
                'initial_position': agent.get('position'),
                'max_autonomy': agent.get('autonomy'),
                'current_autonomy': agent.get('current_autonomy')
            }
        self.agents = agents

    def init_joint_plan(self):
        self.joint_plan = {"no_change": [], "joint": None, "table_of_goals": {}, "individual": {}}
        # To indicate end of best response process
        # Initialize joint plan to None
        # Initialize table_of_goals
        # Create an empty plan per transport agent
        for a in self.agents:
            key = a.get('id')
            self.joint_plan["individual"][key] = None
            self.joint_plan["no_change"].append(False)

        for customer in self.config_dic.get("customers"):
            customer_id = customer.get('name')
            self.joint_plan["table_of_goals"][customer_id] = None

    def create_planner(self, agent):
        prev_plan = self.joint_plan.get('individual').get(agent.get('id'))
        agent_planner = Planner(self.config_dic, self.actions_dic, self.routes_dic,
                                agent_id=agent.get('id'),
                                agent_pos=agent.get('initial_position'),
                                agent_max_autonomy=agent.get('max_autonomy'),
                                agent_autonomy=agent.get('current_autonomy'),
                                previous_plan=prev_plan, joint_plan=self.joint_plan)
        return agent_planner

    def has_plan(self, agent):
        return self.joint_plan.get('individual').get(agent.get('id')) is not None

    def get_individual_plan(self, agent):
        return self.joint_plan.get('individual').get(agent.get('id'))

    def evaluate_plan(self, plan):
        # Benefits
        benefits = 0
        for entry in plan.entries:
            action = entry.action
            if action.get('type') == 'MOVE-TO-DEST':
                # CHECK IF I'M THE FIRST ONE PICKING THAT CUSTOMER UP
                plan_owner = action.get('agent')
                customer = action.get('attributes').get('customer_id')
                tup = self.joint_plan.get('table_of_goals').get(customer)
                serving_transport = tup[0]
                if serving_transport == plan_owner:
                    benefits += STARTING_FARE + (action.get('statistics').get('dist') / 1000) * PRICE_PER_KM
        # Costs
        costs = 0
        for entry in plan.entries:
            action = entry.action
            # For actions that entail a movement, pay a penalty per km (10%)
            if action.get('type') != 'CHARGE':
                costs += PENALTY * (action.get('statistics').get('dist') / 1000)
            # For actions that entail charging, pay for the charged electricity
            # TODO
            # price increase if congestion (implementar a futur)
            else:
                costs += PRICE_PER_kWh * action.get('statistics').get('need')
        # Utility (or g value) = benefits - costs
        utility = benefits - costs
        if utility < 0:
            print("THE COSTS ARE HIGHER THANT THE BENEFITS")

        return utility

    def update_joint_plan(self, agent_id, new_plan):
        self.joint_plan["individual"][agent_id] = new_plan
        self.update_table_of_goals()

    def update_table_of_goals(self):
        aux = {}
        # Check table of goals of every individual plan
        for transport in self.joint_plan.get('individual').keys():
            p = self.joint_plan.get('individual').get(transport)
            tog = p.table_of_goals
            for customer in tog.keys():
                if aux.get(customer) is None:
                    aux[customer] = []
                # for each customer, add tuples with every transport that serves him with pick-up time
                aux[customer].append((transport, tog.get(customer)))

        # Then, compare all pick up times for a single customer and decide which transport arrives before
        for customer in aux.keys():
            earliest = min(aux.get(customer), key=lambda x: x[1])
            # Input in the table of goals a tuple with the serving transport id and pick-up time
            self.joint_plan['table_of_goals'][customer] = earliest

    def run(self):
        self.initialize()

        self.create_agents()

        # assign random order
        order = list(self.agents.keys())
        random.shuffle(order)

        self.init_joint_plan()

        game_turn = 0
        while not all(self.joint_plan["changes"]):
            # One turn of the game: each player chooses a machine, one after another
            game_turn += 1
            logger.info("*************************************************************************")
            logger.info(f"\t\t\t\t\t\t\tBest Response turn {game_turn}")
            logger.info("*************************************************************************")
            for a in self.agents:
                agent_id = a.get('id')
                logger.info(f"Agent's {agent_id} turn")
                logger.info("-------------------------------------------------------------------------")

                # If the agent had already proposed a plan before
                if self.has_plan(a):
                    prev_plan = self.get_individual_plan(a)
                    prev_utility = prev_plan.utility
                    updated_utility = self.evaluate_plan(prev_plan)
                    if prev_utility != updated_utility:
                        logger.info(
                            f"Agent {agent_id} had it's plan utility reduced from {prev_utility:.4f} to {updated_utility:.4f}")
                        planner = self.create_planner(a)
                        planner.run()
                        new_plan = planner.plan
                        self.update_joint_plan(agent_id, new_plan)
                        new_utility = self.evaluate_plan(new_plan)
                        logger.info(
                            f"Agent {agent_id} found new plan with utility {new_utility:.4f}")
                    else:
                        logger.info(f"The utility of agent's {agent_id} plan has not changed")

                # If the agent had no plan
                else:
                    logger.info(f"Creating first plan for agent {agent_id}")
                    planner = self.create_planner(a)
                    planner.run()
                    new_plan = planner.plan
                    self.update_joint_plan(agent_id, new_plan)
                    new_utility = self.evaluate_plan(new_plan)
                    logger.info(
                        f"Agent {agent_id} found a plan with utility {new_utility:.4f}")
                logger.info("-------------------------------------------------------------------------")

# begin process
# first player:
#   initialize Planner
#   get Plan and add to joint plan
#   update agent's joint plan
# while there is change in plan utilities
#   select next player
#   if player has previous plan:
#       re-evaluate plan w.r.t new joint plan
#       look for new proposal that improves Utility
#       update proposal in joint plan
#   else:
#       propose plan w.r.t joint plan
#       add Plan to joint plan
