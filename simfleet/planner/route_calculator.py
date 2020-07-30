import asyncio
import json
import sys
from simfleet.helpers import distance_in_meters
from simfleet.utils import request_route_to_server
from generators_utils import has_enough_autonomy, calculate_km_expense

config_dic = {}
global_actions = {}
transport_info = {}
ordered_global_actions = {}

ROUTE_HOST = "http://osrm.gti-ia.upv.es/"


def load_config(config_file):
    config_dic = {}
    try:
        f2 = open(config_file, "r")
        config_dic = json.load(f2)
    except Exception as e:
        print(str(e))
        exit()
    return config_dic


def get_points():
    transports = config_dic.get("transports")
    customers = config_dic.get("customers")
    stations = config_dic.get("stations")
    # Get all initial transport positions
    transport_positions = []
    for transport in transports:
        t_position = transport.get("position")
        transport_positions.append(t_position)

    # Get all station position
    station_positions = []
    for station in stations:
        s_position = station.get("position")
        station_positions.append(s_position)

    # Get customer origin and destination points
    customer_origins = []
    customer_destinations = []
    for customer in customers:
        c_origin = customer.get("position")
        customer_origins.append(c_origin)
        c_dest = customer.get("destination")
        customer_destinations.append(c_dest)

    return transport_positions, station_positions, customer_origins, customer_destinations


"""
routes = {
    ([x1,y1], [x2,y2]) : { path : [], distance : xxxx, duration : xxxx }
}
"""


async def calculate_routes(transport_positions, station_positions, customer_origins, customer_destinations):
    routes = {}
    # Calculate routes between transport positions and station positions
    # used if the transport has to charge before doing any assignment
    for t_pos in transport_positions:
        for s_pos in station_positions:
            path, distance, duration = await request_route_to_server(t_pos, s_pos, ROUTE_HOST)
            # create key and value for routes dic
            key, value = create_key_value(t_pos, s_pos, path, distance, duration)
            # save key and value
            routes[key] = value

    # Calculate routes between transport positions and customer origins
    # used if the transport begin execution with a customer assignment
    for t_pos in transport_positions:
        for c_origin in customer_origins:
            path, distance, duration = await request_route_to_server(t_pos, c_origin, ROUTE_HOST)
            # create key and value for routes dic
            key, value = create_key_value(t_pos, c_origin, path, distance, duration)
            # save key and value
            routes[key] = value

    # Calculate routes between station positions and customer origins
    # used if the transport starts a customer assignment after charging
    for s_pos in station_positions:
        for c_origin in customer_origins:
            path, distance, duration = await request_route_to_server(s_pos, c_origin, ROUTE_HOST)
            # create key and value for routes dic
            key, value = create_key_value(s_pos, c_origin, path, distance, duration)
            # save key and value
            routes[key] = value

    # Calculate routes between customer origins and customer destinations
    # WE ARE CALCULATING PATHS BETWEEN ALL CUSTOMER ORIGINS AND ALL CUSTOMER DESTINATIONS
    # UPDATE IN FUTURE SO THAT ONLY PATHS BETWEEN SAME CUSTOMER ORIGIN AND DEST ARE CALCULATED
    for c_origin in customer_origins:
        for c_dest in customer_destinations:
            path, distance, duration = await request_route_to_server(c_origin, c_dest, ROUTE_HOST)
            # create key and value for routes dic
            key, value = create_key_value(c_origin, c_dest, path, distance, duration)
            # save key and value
            routes[key] = value

    # Calculate routes between customer destinations and station positions
    # used if the transport needs to charge after completing a customer assignment
    for c_dest in customer_destinations:
        for s_pos in station_positions:
            path, distance, duration = await request_route_to_server(c_dest, s_pos, ROUTE_HOST)
            # create key and value for routes dic
            key, value = create_key_value(c_dest, s_pos, path, distance, duration)
            # save key and value
            routes[key] = value

    # Calculate routes between customer destinations and customer origins
    # used if the transport starts a customer assignment after completing a customer assignment
    for c_dest in customer_destinations:
        for c_origin in customer_origins:
            path, distance, duration = await request_route_to_server(c_dest, c_origin, ROUTE_HOST)
            # create key and value for routes dic
            key, value = create_key_value(c_dest, c_origin, path, distance, duration)
            # save key and value
            routes[key] = value

    print(f"{len(routes):4d} routes calculated\n")
    return routes

def create_key_value(k1, k2, path, dist, dur):
    key = str(k1)+":"+str(k2)
    value = {
        "path": path,
        "distance": dist,
        "duration": dur
    }
    return key, value


#######################################################################################################################
#################################################### MAIN #############################################################
#######################################################################################################################


def usage():
    print("Usage: python route_calculator.py <simfleet_config_file> (optional: <output_file_name>)")
    exit()


if __name__ == '__main__':
    config_file = None
    output_file_name = None

    if len(sys.argv) < 2:
        usage()

    config_file = str(sys.argv[1])
    if len(sys.argv) > 2:
        output_file_name = str(sys.argv[2])
        print("Output file name will be: ", output_file_name)

    config_dic = load_config(config_file)
    t, s, co, cd = get_points()
    routes = asyncio.run(calculate_routes(t, s, co, cd))

    outfile = open("routes/20config-routes.json", "w+")
    json.dump(routes, outfile, indent=4)
    outfile.close()
