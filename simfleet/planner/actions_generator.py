# Open a simfleet configuration
# actions = {}
# For every transport:
# transport_actions = {}
# For every customer:
# transport_customer_actions = {}
# create action to take customer to its destination

# For every station:
# transport_charge_actions = {}
# create action to go to the station and charge

"""
actions : {

    "taxi1" : {

        "CUSTOMER_ACTIONS" : [ {"taxi1", "CUSTOMER", "customer1@localhost", [x1,y1], [x2,y2]}, ...],
        "CHARGE_ACTIONS" : [ {"taxi1", "CHARGE", "station1@localhost", [x1,y1]}, ...]

    }

    "taxi2" : {

        "CUSTOMER_ACTIONS" : [...],
        "CHARGE_ACTIONS" : [...],

    }

}

"""
import json
import sys

from generators_utils import has_enough_autonomy, calculate_km_expense

from simfleet.helpers import distance_in_meters
from simfleet.utils import request_route_to_server

config_dic = {}
global_actions = {}
transport_info = {}
ordered_global_actions = {}

ROUTE_HOST = "http://osrm.gti-ia.upv.es/"


def load_config(config_file):
    config_dic = {}
    routes_dic = {}
    try:
        f2 = open(config_file, "r")
        config_dic = json.load(f2)
    except Exception as e:
        print(str(e))
        exit()
    return config_dic


def generate_actions(config_dic):
    actions = {}
    host = config_dic.get("host")
    transports = config_dic.get("transports")
    customers = config_dic.get("customers")
    stations = config_dic.get("stations")

    for transport in transports:
        t_name = transport.get("name")
        t_position = transport.get("position")
        t_max_autonomy = transport.get("autonomy")
        t_current_autonomy = transport.get("current_autonomy")
        t_fleet_type = transport.get("fleet_type")

        # save transport info in a dictionary
        transport_info[t_name] = {
            "position": t_position,
            "max_autonomy": t_max_autonomy,
            "current_autonomy": t_current_autonomy
        }

        transport_actions = {}

        pick_up_actions = []
        dest_actions = []
        for customer in customers:
            # If fleet type coincides, get customer name, origin and destination
            if customer.get("fleet_type") == t_fleet_type:
                # c_name = customer.get("name") + "@" + host
                c_name = customer.get("name")
                c_origin = customer.get("position")
                c_dest = customer.get("destination")

                # Create customer action
                pick_up_action = create_pick_up_action(t_name, c_name, c_origin)
                pick_up_actions.append(pick_up_action)

                dest_action = create_mode_to_dest_action(t_name, c_name, c_origin, c_dest)
                dest_actions.append(dest_action)

        transport_actions["PICK-UP"] = pick_up_actions
        transport_actions["MOVE-TO-DEST"] = dest_actions
        # print(transport_actions["CUSTOMER"])
        # print("\nClosest customer for transport "+t_name)
        # closest_customer_action = get_closest_customer_action(transport_actions, t_position)
        # print(closest_customer_action[0], str(closest_customer_action[1]), "\n")

        station_actions = []
        charge_actions = []
        for station in stations:
            # Get station name, position and power
            # s_name = station.get("name") + "@" + host
            s_name = station.get("name")
            s_position = station.get("position")
            s_power = station.get("power")

            # Create charge action
            station_action = create_move_to_station_action(t_name, s_name, s_position)
            station_actions.append(station_action)
            charge_action = create_charge_action(t_name, s_name, s_power)
            charge_actions.append(charge_action)

        transport_actions["MOVE-TO-STATION"] = station_actions
        transport_actions["CHARGE"] = charge_actions

        actions[t_name] = transport_actions
    # print(actions)
    return actions


# def create_action(agent, type, attributes):
#     if type == "CUSTOMER":
#         return create_customer_action(agent, attributes[0], attributes[1], attributes[2])
#     else:
#         return create_charge_action(agent, attributes[0], attributes[1])


def create_pick_up_action(agent, customer_id, customer_origin):
    # Create action
    action = {}
    # Assign agent and action type
    action["agent"] = agent
    action["type"] = "PICK-UP"
    # Create attributes
    attr = {}
    attr["customer_id"] = customer_id
    attr["customer_origin"] = customer_origin
    # Assign attributes to action
    action["attributes"] = attr
    # Initialise action statistics
    action["statistics"] = {
        "time": None,
        "dist": None
    }

    # action = Action(agent, "CUSTOMER", attr, {})

    return action


def create_mode_to_dest_action(agent, customer_id, customer_origin, customer_dest):
    # Create action
    action = {}
    # Assign agent and action type
    action["agent"] = agent
    action["type"] = "MOVE-TO-DEST"
    # Create attributes
    attr = {}
    attr["customer_id"] = customer_id
    attr["customer_origin"] = customer_origin
    attr["customer_dest"] = customer_dest
    # Assign attributes to action
    action["attributes"] = attr
    # Initialise action statistics
    action["statistics"] = {
        "time": None,
        "dist": None
    }

    # action = Action(agent, "CUSTOMER", attr, {})

    return action


def create_move_to_station_action(agent, station_id, station_position):
    # Create action
    action = {"agent": agent, "type": "MOVE-TO-STATION"}
    # Assign agent and action type
    # Create attributes
    attr = {"station_id": station_id, "station_position": station_position}
    # Assign attributes to action
    action["attributes"] = attr
    # Initialise action statistics
    action["statistics"] = {
        "time": None,
        "dist": None
    }

    return action


def create_charge_action(agent, station_id, power):
    # Create action
    action = {"agent": agent, "type": "CHARGE"}
    # Assign agent and action type
    # Create attributes
    attr = {"station_id": station_id, "power": power}
    # Assign attributes to action
    action["attributes"] = attr
    # Initialise action statistics
    action["statistics"] = {
        "time": None,
        "need": None
    }

    return action


def save_actions(config_file, output_file_name):
    if output_file_name is None:
        try:
            extra = len(config_file.split(".")[1]) + 1
            output_file_name = config_file[:-extra] + "3config-actions.json"
            # print("aslufhauiohfa", output_file_name)
        except Exception as e:
            print(str(e))
            exit()
    else:
        try:
            extra = len(config_file.split(".")[1]) + 1
            output_file_name = output_file_name[:-extra] + "3config-actions.json"
        except Exception as e:
            print(str(e))
            exit()
    save_json(config_file, global_actions, output_file_name)


def save_ordered_actions(config_file, output_file_name):
    if output_file_name is None:
        try:
            extra = len(config_file.split(".")[1]) + 1
            output_file_name = config_file[:-extra] + "-ordered-actions.json"
        except Exception as e:
            print(str(e))
            exit()
    else:
        try:
            extra = len(config_file.split(".")[1]) + 1
            output_file_name = output_file_name[:-extra] + "-ordered-actions.json"
        except Exception as e:
            print(str(e))
            exit()
    save_json(config_file, ordered_global_actions, output_file_name)


def save_json(config_file, dictionary, output_file_name=None):
    # # Write output file
    # if output_file_name is None:
    #     try:
    #         extra = len(config_file.split(".")[1]) + 1
    #         output_file_name = config_file[:-extra] + "3config-actions.json"
    #     except Exception as e:
    #         print(str(e))
    #         exit()
    # try:
    #     if not output_file_name.endswith(".json"):
    #         output_file_name += ".json"
    #     outfile = open(output_file_name, "w+")
    #     json.dump(dictionary, outfile, indent=4)
    #     outfile.close()
    # except Exception as e:
    #     print(str(e))
    #     exit()
    # try:
    # print("asda", output_file_name)
    outfile = open(output_file_name, "w+")
    json.dump(dictionary, outfile, indent=4)
    outfile.close()
    # except Exception as e:
    #    print(str(e))
    #    exit()

    print("SUCCESS: " + output_file_name + " correctly generated.")


def get_closest_customer_action(transport_actions, transport_position):
    """
    closest_station = min(station_positions,
                          key=lambda x: distance_in_meters(x[1], self.agent.get_position()))
    """
    action_list = transport_actions.get("CUSTOMER")
    # aux = []
    # for action in action_list:
    #     customer_origin = action.get("attributes").get("customer_origin")
    #     aux.append((action, distance_in_meters(transport_position, customer_origin)))
    #
    # aux.sort(key=lambda x: x[1])

    closest_action = min(action_list,
                         key=lambda x: distance_in_meters(transport_position,
                                                          x.get("attributes").get("customer_origin")))
    distance = distance_in_meters(transport_position, closest_action.get("attributes").get("customer_origin"))
    return (closest_action, distance)


def get_closest_charge_action(transport_actions, transport_position):
    action_list = transport_actions.get("CHARGE")

    closest_action = min(action_list,
                         key=lambda x: distance_in_meters(transport_position,
                                                          x.get("attributes").get("station_position")))
    distance = distance_in_meters(transport_position, closest_action.get("attributes").get("station_position"))
    return (closest_action, distance)


def get_ordered_action_list(transport):
    # while there are still customer actions to do:
    # get closest customer action
    # if has enough autonomy
    # calculate km expenses
    # update autonomy

    # append action to ordered list

    # update current position

    # delete completed customer action from to-do list

    # else
    # get closest station action
    # append action to ordered list
    # update autonomy
    # update current position
    # Initialize position and autonomy to the ones in the config file
    current_position = transport_info.get(transport).get("position")
    current_autonomy = transport_info.get(transport).get("current_autonomy")
    max_autonomy = transport_info.get(transport).get("max_autonomy")
    # Get transport actions
    transport_action = global_actions.get(transport)
    to_do_list = transport_action.get("CUSTOMER")
    # to save ordered actions
    ordered_actions = {}
    step = 0
    distance = 0
    while len(to_do_list) > 0:
        step += 1
        closest_action = get_closest_customer_action(transport_action, current_position)
        next_action = closest_action[0]
        customer_origin = next_action.get("attributes").get("customer_origin")
        customer_dest = next_action.get("attributes").get("customer_dest")
        # Check if there's enough autonomy to do the closest customer action
        if has_enough_autonomy(current_autonomy, current_position, customer_origin, customer_dest):
            # Update autonomy
            km_expenses = calculate_km_expense(current_position, customer_origin, customer_dest)
            current_autonomy -= km_expenses
            distance += closest_action[1]
            # Update current position
            current_position = customer_dest
            # Add action to ordered action list
            ordered_actions[step] = {"action": next_action, "distance": distance}
            # Delete customer action from to-do list
            to_do_list.remove(next_action)

        # Charge at the closest station
        else:
            next_action = get_closest_charge_action(transport_action, current_position)
            distance += next_action[1]
            next_action = next_action[0]
            station_position = next_action.get("attributes").get("station_position")
            # Update autonomy
            current_autonomy = max_autonomy
            # Update current position
            current_position = station_position
            # Add action to ordered action list
            ordered_actions[step] = {"action": next_action, "distance": distance}

    return ordered_actions


def print_transport_actions(transport):
    dic = ordered_global_actions.get(transport)
    print(
        "Agent " + transport + " actions:\n====================================================================================================================================================================================")
    for step in dic:
        print(f"{step:4d}\t:\t{str(dic.get(step)):200s}")
    print(
        "==========================================================================================================================================================================================================")


async def test_route_calc():
    for key in global_actions.keys():
        for action in global_actions.get(key).get("CUSTOMER"):
            origin = action.get("attributes").get("customer_origin")
            destination = action.get("attributes").get("customer_dest")
            path, distance, duration = await request_route_to_server(origin, destination, ROUTE_HOST)
            print("Path", len(path))
            print("Distance", distance)
            print("Duration", duration, "\n")


#######################################################################################################################
#################################################### MAIN #############################################################
#######################################################################################################################


def usage():
    print("Usage: python action_generator.py <simfleet_config_file> (optional: <output_file_name>)")
    exit()


if __name__ == '__main__':
    config_file = None
    output_file_name = None

    if len(sys.argv) < 2:
        usage()

    config_file = str(sys.argv[1])
    if len(sys.argv) > 2:
        # output_file_name = str(sys.argv[2])
        output_file_name = "actions/problem5-actions.json"
        print("Output file name will be: ", output_file_name)

    config_dic = load_config(config_file)
    global_actions = generate_actions(config_dic)

    # asyncio.run(test_route_calc())

    # for transport in global_actions.keys():
    #     ordered_global_actions[transport] = get_ordered_action_list(transport)
    #     print_transport_actions(transport)
    #
    #
    save_actions(config_file, output_file_name)
    # save_ordered_actions(config_file, output_file_name)
