import copy
import json
import math
import random

from loguru import logger

from simfleet.planner.constants import CONFIG_FILE, ACTIONS_FILE, \
    ROUTES_FILE, INITIAL_GREEDY_PLAN, PRINT_OUTPUT
from simfleet.planner.evaluator import evaluate_plan
from simfleet.planner.plan import JointPlan
from simfleet.planner.planner import Planner

INITIAL_JOINT_PLAN = False
LOOP_DETECTION = True
CONSIDER_PREV_PLAN = False
VERBOSE = 0


class BestResponse:

    def __init__(self, database):
        self.db = database
        # self.config_dic = config_dic
        # self.actions_dic = actions_dic
        # self.routes_dic = routes_dic
        self.joint_plan = None
        self.agents = database.agents
        self.list_of_plans = database.list_of_plans
        self.best_prev_plan = {}
        self.station_usage = {}
        self.power_grids = {1: {'stations': [], 'limit_power': 0}}
        self.planning_times = []

    # Load dictionary data
    def initialize(self):
        try:
            f2 = open(CONFIG_FILE, "r")
            self.config_dic = json.load(f2)

            f2 = open(ACTIONS_FILE, "r")
            self.actions_dic = json.load(f2)

            f2 = open(ROUTES_FILE, "r")
            self.routes_dic = json.load(f2)

        except Exception as e:
            print(str(e))
            exit()

    def update_db(self):
        self.db.joint_plan = self.joint_plan

    def init_station_usage(self):
        for station in self.db.config_dic.get('stations'):
            self.station_usage[station.get('name')] = []

    def init_power_grids(self):
        for station in self.db.config_dic.get('stations'):
            # if the station is assigned to a grid
            if station.get('power_grid') is not None:
                # if the grid already exists
                if self.power_grids.get(station.get('power_grid')) is not None:
                    # add station to stations list
                    self.power_grids[station.get('power_grid')]['stations'].append(station.get('name'))
                    # add station power to maximum grid power
                    self.power_grids[station.get('power_grid')]['limit_power'] += station.get('power')
                # if not
                else:
                    self.power_grids[station.get('power_grid')] = {'stations': [], 'limit_power': 0}
                    self.power_grids[station.get('power_grid')]['stations'] = [station.get('name')]
                    self.power_grids[station.get('power_grid')]['limit_power'] = station.get('power')
            # if there is no grid indicated, add it to grid 1 (global grid)
            else:
                self.power_grids[1]['stations'].append(station.get('name'))
                self.power_grids[1]['limit_power'] += station.get('power')
        # TODO delete later
        if PRINT_OUTPUT > 0:
            for grid in self.power_grids.keys():
                logger.error(f"Power grid {grid:2d}: {self.power_grids[grid]}")

    # Prepares the data structure to store the Joint plan
    def init_joint_plan(self):
        # Initialize joint plan to None
        self.joint_plan = {"station_usage": None, "no_change": {}, "joint": None,
                           "table_of_goals": {}, "individual": {}}

        # Create an empty plan per transport agent
        for a in self.agents:
            key = a.get('id')
            self.joint_plan["individual"][key] = None
            # To indicate end of best response process
            self.joint_plan["no_change"][key] = False

        # Initialize table_of_goals
        for customer in self.db.config_dic.get("customers"):
            customer_id = customer.get('name')
            self.joint_plan["table_of_goals"][customer_id] = (None, math.inf)

        self.init_station_usage()
        self.init_power_grids()
        self.joint_plan["station_usage"] = self.station_usage
        self.joint_plan["power_grids"] = self.power_grids

        self.update_db()

    # Given a transport agent, creates its associated Planner object
    def create_planner(self, agent):
        # prev_plan = self.joint_plan.get('individual').get(agent.get('id'))
        agent_planner = Planner(self.db,
                                agent_id=agent.get('id'),
                                agent_pos=agent.get('initial_position'),
                                agent_max_autonomy=agent.get('max_autonomy'),
                                agent_autonomy=agent.get('current_autonomy'),
                                agent_goals=agent.get('goals'),
                                previous_plan=None)
        return agent_planner

    # Returns true if the transport agent has an individual plan in the joint plan
    def has_plan(self, agent):
        return self.joint_plan.get('individual').get(agent.get('id')) is not None

    # Returns a transport agent's individual plan
    def get_individual_plan(self, agent):
        return self.joint_plan.get('individual').get(agent.get('id'))

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

    # Given a transport agent and a plan associated to it, substitutes the agent individual plan with the new plan
    # and modifies the contents of the joint_plan accordingly
    def update_joint_plan(self, agent_id, new_plan):
        # Update agent's individual plan
        self.joint_plan["individual"][agent_id] = new_plan
        # self.joint_plan["no_change"][agent_id] = False
        # Extract every individual plan action to build the joint plan
        self.extract_joint_plan()
        # Update table_of_goals to match with individual plans
        self.update_table_of_goals()
        # Update station_usage to match with individual plans
        self.update_station_usage()
        # Copy local joint plan into the Database
        self.update_db()

    def update_table_of_goals(self):
        # Restart table of table_of_goals
        for customer in self.db.config_dic.get("customers"):
            customer_id = customer.get('name')
            self.joint_plan["table_of_goals"][customer_id] = (None, math.inf)
        aux = {}

        for entry in self.joint_plan.get("joint").entries:
            action = entry.action
            if action.get('type') == 'PICK-UP':
                agent = action.get('agent')
                customer = action.get('attributes').get('customer_id')
                pick_up_time = entry.end_time
                if aux.get(customer) is None:
                    aux[customer] = []
                # for each customer, add tuples with every transport that serves him with pick-up time
                aux[customer].append((agent, pick_up_time))

        # Then, compare all pick up times for a single customer and decide which transport arrives before
        for customer in aux.keys():
            earliest = min(aux.get(customer), key=lambda x: x[1])
            # Input in the table of goals a tuple with the serving transport id and pick-up time
            self.joint_plan['table_of_goals'][customer] = earliest

    def update_station_usage(self):
        # Clear station usages
        self.init_station_usage()
        # Extract charge actions from the joint plan
        for entry in self.joint_plan.get("joint").entries:
            action = entry.action
            # Create a usage per CHARGE action
            if action.get('type') == 'CHARGE':
                agent = action.get('agent')
                station = action.get('attributes').get('station_id')
                at_station = entry.init_time
                init_charge = action.get('statistics').get('init_charge')
                end_time = entry.end_time
                power = action.get('statistics').get('need')
                inv = action.get('inv')
                # Add usage to the list of usages of the corresponding station
                self.station_usage[station].append({
                    'agent': agent,
                    'at_station': at_station,
                    'init_charge': init_charge,
                    'end_charge': end_time,
                    'power': power,
                    'inv': inv
                })

        # Sort list of usages of every station
        for station in self.station_usage.keys():
            self.station_usage[station].sort(key=lambda x: x.get('at_station'))
        self.joint_plan['station_usage'] = self.station_usage
        self.flag_invalid_usage()

    def get_station_places(self, station_name):
        for station in self.db.config_dic.get('stations'):
            if station.get('name') == station_name:
                return station.get("places")

    def flag_invalid_usage(self):
        for station in self.joint_plan.get('station_usage').keys():
            usage_list = self.joint_plan.get('station_usage').get(station)
            for current_agent in usage_list:
                c = 0
                # logger.critical(f"\nagent is {current_agent}")
                # Compare usage against all other usages which are not itself and are not invalid
                for other_agent in [x for x in usage_list if x.get('agent') != current_agent.get('agent')
                                                             and x.get('inv') is None]:
                    # logger.critical(f"other agent is {other_agent}")
                    if other_agent.get('init_charge') < current_agent.get('init_charge') < other_agent.get(
                        'end_charge'):
                        c += 1
                        # logger.critical("increasing counter")
                    # comencem a carregar alhora però l'altre acaba més tard que jo comence
                    elif other_agent.get('init_charge') == current_agent.get('init_charge') < other_agent.get(
                        'end_charge'):
                        # if the starting times are the same, current agent will only be invalid
                        # if other agent arrived before them
                        if other_agent.get('at_station') < current_agent.get('at_station'):
                            c += 1
                        elif other_agent.get('at_station') == current_agent.get('at_station'):
                            # logger.critical(f"Both agents arrive at the station at the same time and start "
                            #               f"charging at the same time, the sistem does not know which one to flag"
                            #                f"as INVALID. \n{other_agent}\n{current_agent}")
                            c += 1
                            # marcar com a invàlid un dels dos agents amb probabilitat del 50%

                if c >= self.get_station_places(station):
                    # current_agent's usage is invalid
                    # logger.critical(f'INVALID {current_agent}')
                    current_agent['inv'] = 'INV'
                    # To mark it as invalid:
                    #   Go to current_agent's plan, look for the appropriate charge action and flag it
                    # agent = current_agent.get('agent')
                    # agent_plan = self.joint_plan.get('individual').get(agent)
                    # for entry in agent_plan.entries:
                    #     action = entry.action
                    #     if action.get('type') == 'CHARGE':
                    #         if action.get('statistics').get('init_charge') == current_agent.get('init_charge'):
                    #             action['inv'] = 'INV'

                # else:
                #     del current_agent['inv']
                #     # To mark it as invalid:
                #     #   Go to current_agent's plan, look for the appropriate charge action and flag it
                #     agent = current_agent.get('agent')
                #     agent_plan = self.joint_plan.get('individual').get(agent)
                #     for entry in agent_plan.entries:
                #         action = entry.action
                #         if action.get('type') == 'CHARGE':
                #             if action.get('statistics').get('init_charge') == current_agent.get('init_charge'):
                #                 action['inv'] = None

    def flag_invalid_charge_actions(self):
        for station in self.joint_plan.get('station_usage').keys():
            usage_list = self.joint_plan.get('station_usage').get(station)
            for current_agent in usage_list:
                if current_agent.get('inv') == 'INV':
                    agent = current_agent.get('agent')
                    agent_plan = self.joint_plan.get('individual').get(agent)
                    for entry in agent_plan.entries:
                        action = entry.action
                        if action.get('type') == 'CHARGE':
                            if action.get('statistics').get('init_charge') == current_agent.get('init_charge'):
                                action['inv'] = 'INV'
                                agent_plan.inv = True
        self.update_db()

    # Checks stopping criteria of Best Response algorithm
    def stop(self):

        stop_by_loop = False

        # if we are detection loops
        if LOOP_DETECTION:
            # list to store a boolean indicating if an agent is repeating plans
            loops_in_agents = []
            for agent in self.agents:
                loops_in_agents.append(self.check_loop(agent))
                # logger.debug("\n")

            # if all agents are repeating plans, stop_by_loop is True
            stop_by_loop = all(loops_in_agents)

            if stop_by_loop:
                logger.debug("All agents have a loop in their list of plans. Stop by LOOP.")

        stop = True

        # if no agent changed their plan, stop will be True
        for transport in self.joint_plan.get('no_change').keys():
            stop = stop and self.joint_plan.get('no_change').get(transport)

        if stop:
            logger.debug("All agents have kept the same plan. Stop by CONVERGENCE")

        return stop or stop_by_loop

    def create_initial_plans(self):
        for a in self.agents:
            agent_id = a.get('id')
            if PRINT_OUTPUT > 0:
                logger.info(f"Agent \'{agent_id}\''s turn")
                logger.info("-------------------------------------------------------------------------")
                logger.info(f"Creating first plan for agent {agent_id}")
            planner = self.create_planner(a)
            planner.run()
            new_plan = planner.plan
            self.planning_times.append(planner.planning_time)
            self.check_update_joint_plan(agent_id, None, new_plan)

    def create_initial_greedy_plans(self):
        for a in self.agents:
            agent_id = a.get('id')
            if PRINT_OUTPUT > 0:
                logger.info(f"Agent \'{agent_id}\''s turn")
                logger.info("-------------------------------------------------------------------------")
                logger.info(f"Creating GREEDY initial plan for agent {agent_id}")
            planner = self.create_planner(a)
            planner.greedy_initial_plan()
            new_plan = planner.plan
            self.check_update_joint_plan(agent_id, None, new_plan)

    def propose_plan(self, a):
        agent_id = a.get('id')
        if PRINT_OUTPUT > 0:
            logger.info("\n")
            logger.info(f"Agent \'{agent_id}\''s turn")
            logger.info("-------------------------------------------------------------------------")
        # Get plan from previous round
        prev_plan = self.get_individual_plan(a)
        # if previous plan is None (or Empty), indicates the agent could not find a plan in the previous round
        if prev_plan is None:
            if PRINT_OUTPUT > 0:
                logger.info(f"Agent {agent_id} has no previous plan")
        else:
            # Get previous plan utility
            prev_utility = prev_plan.utility
            # Calculate updated utility w.r.t. other agent's plans
            # CANVI
            updated_utility = evaluate_plan(prev_plan, self.db)
            # updated_utility = self.evaluate_plan(prev_plan)
            if prev_utility != updated_utility:
                if PRINT_OUTPUT > 0:
                    logger.warning(f"Agent {agent_id} had its plan utility reduced "
                                   f"from {prev_utility} to {updated_utility}")
                    # f"from {prev_utility:.4f} to {updated_utility:.4f}")
                # NEW if the utility of the plan had changed, update it in the joint plan
                prev_plan.utility = updated_utility
                self.joint_plan["individual"][agent_id].utility = updated_utility

            else:
                if PRINT_OUTPUT > 0:
                    logger.info(f"The utility of agent's {agent_id} plan has not changed")

        # Propose new plan as best response to joint plan
        if PRINT_OUTPUT > 0:
            logger.info("Searching for new plan proposal...")
        planner = self.create_planner(a)
        planner.run()
        new_plan = planner.plan
        self.planning_times.append(planner.planning_time)

        self.check_update_joint_plan(agent_id, prev_plan, new_plan)

    def check_update_joint_plan(self, agent_id, prev_plan, new_plan):

        # Case 1) Agent finds no plan or a plan with negative utility (only costs)
        if new_plan is None:
            # if both the previous and new plans where None, indicate that the agent did not change its proposal
            if prev_plan is None:
                if PRINT_OUTPUT > 0:
                    logger.error(
                        f"Agent {agent_id} could not find any plan"
                    )
                self.update_joint_plan(agent_id, new_plan)
                if PRINT_OUTPUT > 0:
                    logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                self.joint_plan["no_change"][agent_id] = True

            else:
                # the planner did not find any feasible plan (utility of prev plan was negative but planner returned None)
                if prev_plan.utility < 0:
                    if PRINT_OUTPUT > 0:
                        logger.error(
                            f"Agent {agent_id} could not find any plan"
                        )
                    self.update_joint_plan(agent_id, new_plan)
                    if PRINT_OUTPUT > 0:
                        logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                    self.joint_plan["no_change"][agent_id] = False

                # the planner found the same plan as before (utility of prev plan was positive but planner retuned None)
                # Case 3) Agent finds the same plan it had proposed before
                else:
                    # logger.error(
                    #     f"Agent {agent_id} could not find any plan"
                    # )
                    # self.update_joint_plan(agent_id, new_plan)
                    # logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                    # self.joint_plan["no_change"][agent_id] = False
                    # logger.critical("NO DEURIA ENTRAR ACÍ")
                    if PRINT_OUTPUT > 0:
                        logger.error(
                            f"Agent {agent_id} could not improve its previous plan (it found the same one than in the previous round)")
                    self.joint_plan["no_change"][agent_id] = True

        # Planner returns something that is not NONE
        else:

            new_utility = new_plan.utility
            # if the prev_plan was None (either 1st turn or couldn't find plan last round) accept new plan
            if prev_plan is None:
                if PRINT_OUTPUT > 0:
                    logger.warning(
                        f"Agent {agent_id} found a plan with utility {new_utility:.4f}")
                    logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                self.update_joint_plan(agent_id, new_plan)
                self.joint_plan["no_change"][agent_id] = False
            # if new_plan.equals(prev_plan):
            #     logger.critical(f"Agent {agent_id} found the same plan as previous round")
            # Case 2) Agent finds a new plan that improves its utility
            elif not new_plan.equals(prev_plan):  # != prev_plan.utility:
                if PRINT_OUTPUT > 0:
                    logger.warning(
                        f"Agent {agent_id} found new plan with utility {new_utility}")
                    logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                self.update_joint_plan(agent_id, new_plan)
                self.joint_plan["no_change"][agent_id] = False

                # Check for loops
                # self.check_loop(agent_id, new_plan)

                # Update list of plans
                if LOOP_DETECTION:
                    self.update_list_of_plans(agent_id, new_plan)

            # Case 3) Agent finds the same plan it had proposed before
            elif new_plan.equals(prev_plan):
                logger.critical("NO DEURIA ENTRAR ACÍ")
                logger.info(
                    f"Agent {agent_id} could not find a better plan (it found the same one than in the previous round)")
                self.update_joint_plan(agent_id, new_plan)
                self.joint_plan["no_change"][agent_id] = True

    # Keeps an updated list of the last 3 plans
    def update_list_of_plans(self, agent, new_plan):

        self.list_of_plans[agent].append(copy.deepcopy(new_plan))

        if len(self.list_of_plans[agent]) > 6:
            self.list_of_plans[agent].pop(0)

    def check_loop(self, agent):

        detections = 0
        agent_id = agent.get('id')
        # Check for loops in the Table of Goals
        for i in range(len(self.list_of_plans[agent_id])):
            for j in range(i + 1, len(self.list_of_plans[agent_id])):
                if self.list_of_plans[agent_id][i].equals(self.list_of_plans[agent_id][j]):
                    if PRINT_OUTPUT > 0:
                        logger.critical(f'Detected loop in agent {agent_id} plans in indexes {i} and {j}')
                    detections += 1
                    plan1 = self.list_of_plans[agent_id][i]
                    plan2 = self.list_of_plans[agent_id][j]
                    # logger.info(f'Index {i}, plan {plan1.to_string_plan()}')
                    # logger.info(f'Index {j}, plan {plan2.to_string_plan()}')

        if detections > 0:
            if PRINT_OUTPUT > 0:
                logger.critical(f"Agent {agent_id} has {detections} pairs of equal plans in the list of previous plans")
            return True
        return False

    def print_game_state(self, game_turn):
        logger.debug("\n")
        logger.debug("#########################################################################")
        logger.debug("CURRENT GAME STATE")
        logger.debug(f"Best Response turn {game_turn}")
        self.db.print_joint_plan()

    def run(self):

        # Assign random player order
        # random.shuffle(self.agents)
        # logger.debug("ATTENTION, NOT RANDOMIZING ORDER")
        if PRINT_OUTPUT > 0:
            logger.warning("ATTENTION, RANDOMIZING ORDER")
            logger.debug(f"Agent order {self.agents}")

        # Initialize data structure
        self.init_joint_plan()

        game_turn = 0
        i = 0
        while not self.stop() and game_turn < 1000:  # 1000
            i += 1
            game_turn += 1
            if PRINT_OUTPUT > 0:
                logger.info("*************************************************************************")
                logger.info(f"\t\t\t\t\t\t\tBest Response turn {game_turn}")
                logger.info("*************************************************************************")
            # First turn of the game, agents propose their initial plan
            if game_turn == 1 and INITIAL_GREEDY_PLAN:
                self.create_initial_greedy_plans()
            elif game_turn == 1 and not INITIAL_JOINT_PLAN:
                self.create_initial_plans()
            # In the following turns, the agents may have one of this two:
            # 1) A previous plan
            # 2) An empty plan, because it can't do any action that increases its utility
            if game_turn > 1:
                for a in self.agents:
                    self.propose_plan(a)
            self.flag_invalid_charge_actions()
            if PRINT_OUTPUT > 0:
                self.print_game_state(game_turn)
        logger.info(f"Best Response turn {game_turn}")
        logger.info("END OF GAME")
        avg_reachable_stations = sum(self.db.reachable_stations) / len(self.db.reachable_stations)
        logger.info(f"Avg. reachable stations: {avg_reachable_stations}")
        avg_planning_time = sum(self.planning_times) / len(self.planning_times)
        logger.debug(f"Agents planned {len(self.planning_times)} times. Avg. planning time: {avg_planning_time:.3f}")


if __name__ == '__main__':
    logger.error("To test the Best-Response algorithm please execute launcher.py")
