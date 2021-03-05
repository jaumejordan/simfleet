import copy

from loguru import logger

from best_response import BestResponse
from database import Database
from evaluator import evaluate_plan


class GreedySolver:

    def __init__(self):
        self.joint_plan = None
        # self.station_usage = None
        # Load database
        self.db = Database()
        # Create Best Response instance
        self.br = BestResponse(self.db)
        self.br.init_joint_plan()

    def get_initial_greedy_plans(self):
        # Get initial greedy plans in br.joint_plan
        self.br.create_initial_greedy_plans()
        self.br.flag_invalid_charge_actions()
        self.joint_plan = copy.deepcopy(self.br.joint_plan)
        # self.station_usage = copy.deepcopy(self.br.station_usage)
        logger.info(f"GREEDY PLANS")
        self.db.print_joint_plan()

    def update_br(self):
        # Copy local individual plans into BR's joint plan
        self.br.joint_plan = copy.deepcopy(self.joint_plan)
        # Extract every individual plan actions to build the joint plan
        self.br.extract_joint_plan()
        # Update table_of_goals to match with individual plans
        self.br.update_table_of_goals()
        # Update station_usage to match with individual plans
        self.br.update_station_usage()
        # Flag invalid charge actions
        self.br.flag_invalid_charge_actions()
        # Copy BR's joint plan into the Database
        self.br.update_db()

        # Update local joint plan copy
        self.update_greedy_solver()

    def update_greedy_solver(self):
        self.joint_plan = copy.deepcopy(self.br.joint_plan)

    def fix_times(self):
        # for every agent's invidiual plan
        for agent in self.joint_plan.get('individual').keys():
            agent_plan = self.joint_plan.get('individual').get(agent)
            i = 0
            # if the plan is invalid
            if agent_plan.inv:
                # for every plan entry
                for i in range(1, len(agent_plan.entries)):
                    entry = agent_plan.entries[i]
                    action = entry.action
                    first_invalid_usage = None
                    # Get the first invalid charge action and its attributes
                    if action.get('type') == 'CHARGE' and action.get('inv') == 'INV':
                        # unflag action
                        action['inv'] = None

                        station = action.get('attributes').get('station_id')
                        at_station = action.get('statistics').get('at_station')
                        invalid_init_charge = action.get('statistics').get('init_charge')

                        # Compute the charge_time
                        charging_time = action.get('statistics').get('need') / action.get('attributes').get('power')

                        # Calculate the new waiting time
                        #   for this, calculate the real_init_charge time
                        queue, check = self.db.check_station_queue(agent, station, at_station)
                        # Get que last X agents of the queue which are in front of you, where X is the number of poles
                        # if check, there are more agents in front of me than places in the station
                        if check:
                            # keep only last X to arrive
                            queue = queue[-self.db.get_station_places(station):]
                        # if not check, there are as many agents in front of me as places in the station
                        end_times = [x.get('end_charge') for x in queue]

                        # Real init charge time instant
                        real_init_charge = min(end_times)
                        # Time increment
                        time_increment = real_init_charge - invalid_init_charge
                        if time_increment < 0:
                            logger.critical(
                                "The increment of time in an invalid charge action was negative: \n "
                                f"invalid: {invalid_init_charge}, real: {real_init_charge}, "
                                f"increment: {time_increment}")
                            exit()

                        waiting_time = real_init_charge - at_station

                        # update action statistics
                        action['statistics']['init_charge'] = real_init_charge
                        total_time = charging_time + waiting_time
                        action['statistics']['time'] = total_time

                        # Update times of the associated plan entry
                        entry.duration = action.get('statistics').get('time')
                        entry.end_time = entry.init_time + entry.duration

                        # Once the first invalid charge is updated, break the loop and update all other plan entries
                        break

                        # NOT NECESSARY, AS THE STATION_USAGE WILL BE UPDATED BY THE BR LATER
                        # V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V
                        # # Get the associated invalid station usage
                        # for usage in self.joint_plan.get('station_usage').get(station):
                        #     if usage.get('inv') == 'INV':
                        #         # Doublecheck they make reference to the same charge
                        #         if self.are_same_charge(action, usage):
                        #
                        #             # Correct usage times
                        #             at_station = usage.get('at_station')
                        #             invalid_init_charge = usage.get('init_charge')
                        #
                        #             queue, check = self.db.check_station_queue(agent, station, at_station)
                        #             # Get que last X agents of the queue which are in front of you, where X is the number of poles
                        #             # if check, there are more agents in front of me than places in the station
                        #             if check:
                        #                 # keep only last X to arrive
                        #                 queue = queue[-self.db.get_station_places(station):]
                        #             # if not check, there are as many agents in front of me as places in the station
                        #             end_times = [x.get('end_charge') for x in queue]
                        #
                        #             # Get charge init time
                        #             real_init_charge = min(end_times)
                        #             time_increment = real_init_charge - invalid_init_charge
                        #             if time_increment < 0:
                        #                 logger.critical(
                        #                     "The increment of time in an invalid charge action was negative: \n "
                        #                     f"invalid: {invalid_init_charge}, real: {real_init_charge}, "
                        #                     f"increment: {time_increment}")
                        #                 exit()
                        #
                        #             # Update times of the previously invalid usage
                        #             usage['init_charge'] = real_init_charge
                        #             usage['end_charge'] = usage.get('end_charge') + time_increment
                        #             usage['inv'] = None
                        #             first_invalid_usage = usage
                        #             break
                        # end of usage for

                        # if first_invalid_usage is not None:
                        #     # * --------------- Update times of the previously invalid action --------------- *
                        #     action.get('statistics')['init_charge'] = first_invalid_usage.get('init_charge')
                        #     # total action time == waiting_time + charge_time
                        #     action.get('statistics')['time'] = first_invalid_usage.get('end_charge') - action.get('statistics').get('at_station')
                        #
                        #     # flag action as valid
                        #     action['inv'] = None
                        #
                        #     # Update times of the associated plan entry
                        #     entry.duration = action. action.get('statistics').get('time')
                        #     entry.end_time = entry.init_time + entry.duration
                        #
                        # else:
                        #     logger.critical(f"Couldn't find a station usage associated to the invalid charge action:\n{action}")
                        #     exit()
                    # end of action if

                    # break

                # end of plan.entries for

                # At this point the invalid entry has been corrected as well as its associated station usage
                # variable i marks the position of the first previously invalid plan entry

                # - Update times of every other action of the plan and their associated station usages (if any) -
                for j in range(i + 1, len(agent_plan.entries)):
                    previous_entry = agent_plan.entries[j - 1]
                    current_entry = agent_plan.entries[j]
                    time_increment = previous_entry.end_time - current_entry.init_time
                    if time_increment < 0:
                        logger.critical(
                            "The increment of time for the plan was negative: \n "
                            f"previous_entry.end_time: {previous_entry.end_time} - current_entry.init_time: {current_entry.init_time} ="
                            f"increment: {time_increment}")
                        exit()
                    # Update entry's action time according to action type:
                    action = current_entry.action

                    if action.get('type') in ['PICK-UP', 'MOVE-TO-DEST', 'MOVE-TO-STATION']:
                        action.get('statistics')['init'] = action.get('statistics').get('init') + time_increment
                    else:  # charge action
                        # unflag action, if it turns out invalid the BR will flag it again
                        action['inv'] = None

                        # update action times
                        action['statistics']['at_station'] = action.get('statistics').get('at_station') + time_increment
                        # Assume the agent will be able to charge upon arrival
                        # if this is incorrect, the next call to update_times will solve it
                        action['statistics']['init_charge'] = action.get('statistics').get('at_station')
                        charging_time = action.get('statistics').get('need') / action.get('attributes').get('power')
                        # action duration: since we assume at_station == init_charge, it is only the charging_time
                        action['statistics']['time'] = charging_time

                        # NOT NECESSARY, AS THE STATION_USAGE WILL BE UPDATED BY THE BR LATER
                        # V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V
                        # localize usage associated to the charge action to be updated
                        # station = action.get('attributes').get('station_id')
                        # for usage in self.joint_plan.get('station_usage').get(station):
                        #     if self.are_same_charge(action, usage):
                        #         usage['inv'] = None
                        #         # Update at_station time
                        #         usage['at_station'] = usage.get('at_station') + time_increment
                        #         # Get charge_time
                        #         charge_time = usage.get('end_charge') - usage.get('init_charge')
                        #         # Assume the agent will be able to charge upon arrival
                        #         # if this is incorrect, the next iteration of update_times will solve it
                        #         usage['init_charge'] = usage.get('at_station')
                        #         # update end_charge with the expected charge_time
                        #         usage['end_charge'] = usage.get('init_charge') + charge_time
                        #     break

                        # # update action time after usage
                        # action.get('statistics')['at_station'] = usage.get('at_station')
                        # action.get('statistics')['init_charge'] = usage.get('init_charge')
                        # action.get('statistics')['time'] = usage.get('end_charge') - action.get(
                        #     'statistics').get('at_station')

                    # end of action.type if

                    # finally, update entry times
                    current_entry.init_time = previous_entry.end_time
                    current_entry.duration = action.get('statistics').get('time')
                    current_entry.end_time = current_entry.init_time + current_entry.duration
                # end of posterior plan entries for

            # end of agent_plan.inv if

            agent_plan.inv = None
        # end of agent individual plans for

        # At this point, any plan with an invalid charge has had its times updated
        # it is necessary to (1) update the joint plan, (2) update station usage and (3) flag invalid usages again
        # if after this process there are any invalid usages, call update_times again

    # def are_same_charge(self, action, usage):
    #     return action.get('agent') == usage.get('agent') and \
    #            action.get('statistics').get('at_station') == usage.get('at_station') and \
    #            action.get('statistics').get('init_charge') == usage.get('init_charge')

    # Return true if there is any plan with an invalid action in the joint plan
    def invalid_joint_plan(self):
        for agent in self.joint_plan.get('individual').keys():
            agent_plan = self.joint_plan.get('individual').get(agent)
            if agent_plan.inv:
                return True
        return False

    # def update_action_times(self):
    #     for station in self.joint_plan.get('station_usage').keys():
    #         for usage in self.joint_plan.get('station_usage').get(station):
    #             if usage.get('inv') == 'INV':
    #                 agent = usage.get('agent')
    #                 at_station = usage.get('at_station')
    #                 invalid_init_charge = usage.get('init_charge')
    #                 # Detected charge which starts at an invalid time
    #                 queue, check = self.db.check_station_queue(agent, station, at_station)
    #                 # Get que last X agents of the queue which are in front of you, where X is the number of poles
    #                 # if check, there are more agents in front of me than places in the station
    #                 if check:
    #                     # keep only last X to arrive
    #                     queue = queue[-self.db.get_station_places(station):]
    #                 # if not check, there are as many agents in front of me as places in the station
    #                 end_times = [x.get('end_charge') for x in queue]
    #                 # FOR ERROR DEBUGGING
    #                 # try:
    #                     # Get charge init time
    #                 real_init_charge = min(end_times)
    #                 time_increment = real_init_charge - invalid_init_charge
    #                 if time_increment < 0:
    #                     logger.critical("The increment of time in an invalid charge action was negative: \n "
    #                                     f"invalid: {invalid_init_charge}, real: {real_init_charge}, "
    #                                     f"increment: {time_increment}")
    #
    #                 # Update times of the previously invalid usage
    #                 usage['init_charge'] = real_init_charge
    #                 usage['end_charge'] = usage.get('end_charge') + time_increment
    #                 usage['inv'] = None
    #
    #                 # Update agent plan
    #                 self.update_plan_times(agent, station, usage, time_increment)
    #
    #                 # Unflag other charges of the agent that take place on

    # def update_plan_times(self, agent, station, usage, time_increment):
    #     agent_plan = self.joint_plan.get('individual').get(agent)
    #     for i in range(len(agent_plan.entries)):
    #         entry = agent_plan.entries[i]
    #         action = entry.action
    #         if action.get('inv') == 'INV': # if action.get('type') == 'CHARGE':
    #             if action.get('attributes').get('station_id') == station:
    #                 if action.get('statistics').get('init_charge') == usage.get('init_charge'):
    #
    #                     action['inv'] = 'INV'
    #                     agent_plan.inv = True

    def evaluate_with_congestion(self):
        for agent in self.joint_plan.get('individual').keys():
            agent_plan = self.joint_plan.get('individual').get(agent)
            updated_utility, _ = evaluate_plan(agent_plan, self.db)
            agent_plan.utility = updated_utility
        self.update_br()


if __name__ == '__main__':
    gs = GreedySolver()
    gs.get_initial_greedy_plans()
    c = 0
    # We give it 100 iterations of fix_times to get a conflictless plan
    while gs.invalid_joint_plan() and c < 100:
        logger.warning(c)
        gs.fix_times()
        gs.update_br()
        c += 1
    gs.evaluate_with_congestion()
    gs.db.print_joint_plan()
