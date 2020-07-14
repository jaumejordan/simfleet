import json
import random

from simfleet.planner.plan import JointPlan
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

    # Load dictionary data
    def initialize(self):
        try:
            f2 = open("3_planner_config.json", "r")
            self.config_dic = json.load(f2)

            f2 = open("test-actions.json", "r")
            self.actions_dic = json.load(f2)

            f2 = open("all-routes.json", "r")
            self.routes_dic = json.load(f2)

        except Exception as e:
            print(str(e))
            exit()

    # Creates Transport Agents that will act as players in the Best Response game
    def create_agents(self):
        agents = []
        for agent in self.config_dic.get('transports'):
            agent_id = agent.get('name')
            agent_dic = {
                'id': agent_id,
                'initial_position': agent.get('position'),
                'max_autonomy': agent.get('autonomy'),
                'current_autonomy': agent.get('current_autonomy')
            }
            agents.append(agent_dic)
        self.agents = agents

        logger.debug(f"Agents loaded {self.agents}")

    # Prepares the data structure to store the Joint plan
    def init_joint_plan(self):
        # Initialize joint plan to None
        self.joint_plan = {"no_change": {}, "joint": None, "table_of_goals": {}, "individual": {}}
        # Create an empty plan per transport agent
        for a in self.agents:
            key = a.get('id')
            self.joint_plan["individual"][key] = None
            # To indicate end of best response process
            self.joint_plan["no_change"][key] = False

        # Initialize table_of_goals
        for customer in self.config_dic.get("customers"):
            customer_id = customer.get('name')
            self.joint_plan["table_of_goals"][customer_id] = None

    # Given a transport agent, creates its associated Planner object
    def create_planner(self, agent):
        prev_plan = self.joint_plan.get('individual').get(agent.get('id'))
        agent_planner = Planner(self.config_dic, self.actions_dic, self.routes_dic,
                                agent_id=agent.get('id'),
                                agent_pos=agent.get('initial_position'),
                                agent_max_autonomy=agent.get('max_autonomy'),
                                agent_autonomy=agent.get('current_autonomy'),
                                previous_plan=prev_plan, joint_plan=self.joint_plan)
        return agent_planner

    # Returns true if the transport agent has an individual plan in the joint plan
    def has_plan(self, agent):
        return self.joint_plan.get('individual').get(agent.get('id')) is not None

    # Returns a transport agent's individual plan
    def get_individual_plan(self, agent):
        return self.joint_plan.get('individual').get(agent.get('id'))

    # Calculates the utility of an individual plan w.r.t. the actions and goals in the Joint plan
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
                # if no one is serving the transport
                if tup is None:
                    benefits += STARTING_FARE + (action.get('statistics').get('dist') / 1000) * PRICE_PER_KM
                else:
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

    # Given a transport agent and a plan associated to it, substitutes the agent individual plan with the new plan
    # and modifies the contents of the joint_plan accordingly
    def update_joint_plan(self, agent_id, new_plan):
        # Update agent's individual plan
        self.joint_plan["individual"][agent_id] = new_plan
        self.joint_plan["no_change"][agent_id] = False
        # Update table_of_goals to match with individual plans
        self.update_table_of_goals()
        # Extract every individual plan action to build the joint plan
        self.extract_joint_plan()

    # Reads all tables of goals of individual plans and creates a global table of goals indicating, per each customer
    # the serving transport and the pick-up time
    def update_table_of_goals(self):
        aux = {}
        # Check table of goals of every individual plan

        for transport in self.joint_plan.get('individual').keys():
            p = self.joint_plan.get('individual').get(transport)
            if p is None:
                continue
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

    # Joins the actions of all individual plans and orders them to create the joint plan
    def extract_joint_plan(self):
        all_entries = []
        for transport in self.joint_plan.get('individual').keys():
            plan = self.joint_plan.get('individual').get(transport)
            if plan is None:
                continue
            for entry in plan.entries:
                all_entries.append(entry)

        # Order actions by init_time
        all_entries.sort(key=lambda x: x.init_time)
        self.joint_plan["joint"] = JointPlan(all_entries)

    # Checks stopping criteria of Best Response algorithm
    def stop(self):
        stop = True
        # if no agent changed their plan, stop will be True
        for transport in self.joint_plan.get('no_change').keys():
            stop = stop and self.joint_plan.get('no_change').get(transport)
        return stop
        #return not all(self.joint_plan["no_change"])

    # Best Response algorithm
    def run(self):
        # Read dictionary data
        self.initialize()
        # Create players
        self.create_agents()

        # Assign random order
        random.shuffle(self.agents)
        logger.debug(f"Random order {self.agents}")

        # Initialize data structure
        self.init_joint_plan()

        game_turn = 0
        while not self.stop():
            game_turn += 1
            logger.info("*************************************************************************")
            logger.info(f"\t\t\t\t\t\t\tBest Response turn {game_turn}")
            logger.info("*************************************************************************")
            if game_turn > 1:
                logger.debug(f"Joint plan in turn {game_turn}")
                logger.debug(self.joint_plan.get('joint').print_plan())
            for a in self.agents:
                agent_id = a.get('id')
                logger.info(f"Agent \'{agent_id}\''s turn")
                logger.info("-------------------------------------------------------------------------")

                # If the agent had already proposed a plan before
                if self.has_plan(a):
                    prev_plan = self.get_individual_plan(a)
                    prev_utility = prev_plan.utility
                    updated_utility = self.evaluate_plan(prev_plan)
                    if prev_utility != updated_utility:
                        logger.info(f"Agent {agent_id} had it's plan utility reduced "
                            f"from {prev_utility:.4f} to {updated_utility:.4f}")
                    else:
                        logger.info(f"The utility of agent's {agent_id} plan has not changed")
                    # New plan proposal
                    planner = self.create_planner(a)
                    planner.run()
                    new_plan = planner.plan
                    self.update_joint_plan(agent_id, new_plan)
                    new_utility = self.evaluate_plan(new_plan)
                    # If the utility is the same, assume plan did not change
                    # TODO compare plans action by action not just by their utility
                    if new_utility != updated_utility:
                        logger.info(
                            f"Agent {agent_id} found new plan with utility {new_utility:.4f}")
                        logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")

                    else:
                        logger.info(f"Agent {agent_id} could not find a better plan")
                        self.joint_plan["no_change"][agent_id] = True

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

if __name__ == '__main__':

    br = BestResponse()
    br.run()
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
