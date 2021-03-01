import asyncio
import copy
import gzip
import json
import math
import sys

import aiohttp

config_dic = {}
global_actions = {}
transport_info = {}
ordered_global_actions = {}

ROUTE_HOST = "http://osrm.gti-ia.upv.es/"

counter = 0
counter_previous = 0
previous_routes = {}


async def request_route_to_server(origin, destination, route_host="http://router.project-osrm.org/"):
    """
    Queries the OSRM for a path.

    Args:
        origin (list): origin coordinate (longitude, latitude)
        destination (list): target coordinate (longitude, latitude)
        route_host (string): route to host server of OSRM service

    Returns:
        list, float, float = the path, the distance of the path and the estimated duration
    """
    try:

        url = route_host + "route/v1/car/{src1},{src2};{dest1},{dest2}?geometries=geojson&overview=full"
        src1, src2, dest1, dest2 = origin[1], origin[0], destination[1], destination[0]
        url = url.format(src1=src1, src2=src2, dest1=dest1, dest2=dest2)

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()

        path = result["routes"][0]["geometry"]["coordinates"]
        path = [[point[1], point[0]] for point in path]
        duration = result["routes"][0]["duration"]
        distance = result["routes"][0]["distance"]
        if path[-1] != destination:
            path.append(destination)
        return path, distance, duration
    except Exception as e:
        return None, None, None


def load_config(config_file):
    config_dic = {}
    try:
        with open(config_file, 'r') as f:
            config_dic = json.load(f)
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
    # customer_origins = []
    # customer_destinations = []
    customer_points = []
    for customer in customers:
        c_origin = customer.get("position")
        # customer_origins.append(c_origin)
        c_dest = customer.get("destination")
        # customer_destinations.append(c_dest)
        customer_points.append((c_origin, c_dest))

    return transport_positions, station_positions, customer_points  # customer_origins, customer_destinations


"""
routes = {
    ([x1,y1], [x2,y2]) : { path : [], distance : xxxx, duration : xxxx }
}
"""


async def calculate_routes(transport_positions, station_positions,
                           customer_points):  # customer_origins, customer_destinations):
    routes = {}
    # Number of customers each agent will initially pick up
    customers = copy.deepcopy(customer_points)
    customers_per_agent = math.ceil(len(customers) / len(transport_positions))
    print(f"customers: {len(customers)}. customers_per_agent: {customers_per_agent}")
    transport_goals = []
    customer_assigned_transport = []
    transport_index = 0
    for _ in transport_positions:
        if len(customers) >= customers_per_agent:
            # Assign their customers
            goals = customers[0:customers_per_agent]
            customers = customers[customers_per_agent:]  # [c for c in customers if c not in goals]
        else:
            goals = copy.deepcopy(customers)  # customers.copy())

        transport_goals.append(goals)
        for _ in goals:
            customer_assigned_transport.append(transport_index)
        transport_index += 1

    # Calculate routes between transport positions and station positions
    # used if the transport has to charge before doing any assignment
    print("Calculating transport-station routes...")
    for t_pos in transport_positions:
        for s_pos in station_positions:
            key, value = await get_route(t_pos, s_pos)
            # save key and value
            routes[key] = value

    # Calculate routes between transport positions and customer origins
    # used if the transport begin execution with a customer assignment
    print("\nCalculating transport-customer routes...")
    for transport_index, t_pos in enumerate(transport_positions):
        for tup in transport_goals[transport_index]:
            c_origin = tup[0]
            key, value = await get_route(t_pos, c_origin)
            # save key and value
            routes[key] = value

    # Calculate routes between station positions and customer origins
    # used if the transport starts a customer assignment after charging
    print("\nCalculating station-customer routes...")
    for s_pos in station_positions:
        for tup in customer_points:
            c_origin = tup[0]
            key, value = await get_route(s_pos, c_origin)
            # save key and value
            routes[key] = value

    # Calculate routes between customer origins and customer destinations
    # WE ARE CALCULATING PATHS BETWEEN ALL CUSTOMER ORIGINS AND ALL CUSTOMER DESTINATIONS
    # UPDATE IN FUTURE SO THAT ONLY PATHS BETWEEN SAME CUSTOMER ORIGIN AND DEST ARE CALCULATED
    print("\nCalculating origin-destination routes...")
    for tup in customer_points:
        c_origin = tup[0]
        c_dest = tup[1]
        key, value = await get_route(c_origin, c_dest)
        # save key and value
        routes[key] = value

    # Calculate routes between customer destinations and station positions
    # used if the transport needs to charge after completing a customer assignment
    print("\nCalculating destination-station routes...")
    for tup in customer_points:
        c_dest = tup[1]
        for s_pos in station_positions:
            key, value = await get_route(c_dest, s_pos)
            # save key and value
            routes[key] = value

    # Calculate routes between customer destinations and customer origins
    # used if the transport starts a customer assignment after completing a customer assignment
    print("\nCalculating destination-origin routes...")
    for customer_index, tup1 in enumerate(customer_points):
        c_dest = tup1[1]
        transport = customer_assigned_transport[customer_index]
        for tup2 in transport_goals[transport]:
            # if tup1 == tup2:
            #    continue
            c_origin = tup2[0]
            key, value = await get_route(c_dest, c_origin)
            # save key and value
            routes[key] = value

    print(f"\n\n{len(routes)} routes in outfile\n")
    print(f"{counter} routes obtained from server")
    print(f"{counter_previous} routes obtained from previous routes")

    return routes


async def get_route(origin, destination):
    global counter_previous, counter
    key = create_key(origin, destination)
    if key in previous_routes:
        value = previous_routes[key]
        counter_previous += 1
        if counter_previous % 100 == 0:
            print(f"Previous {counter_previous} route(s)")
    else:
        path, distance, duration = await request_route_to_server(origin, destination, ROUTE_HOST)
        counter += 1
        if counter % 100 == 0:
            print(f"Calculated {counter} route(s)")
        # create value for routes dic
        value = create_value(path, distance, duration)
    return key, value


def create_key(k1, k2):
    key = str(k1) + ":" + str(k2)
    return key


def create_value(path, dist, dur):
    value = {
        "path": path,
        "distance": dist,
        "duration": dur
    }
    return value


#######################################################################################################################
#################################################### MAIN #############################################################
#######################################################################################################################


def usage():
    print("Usage: python route_calculator.py <simfleet_config_file> <output_file_name>")
    exit()


def read_routes_gzip(filename):
    with gzip.open(filename, 'r') as fin:  # 4. gzip
        json_bytes = fin.read()  # 3. bytes (i.e. UTF-8)

    json_str = json_bytes.decode('utf-8')  # 2. string (i.e. JSON)
    data = json.loads(json_str)
    return data


def store_routes_json(data, filename):
    with open(filename, 'w') as fout:
        json.dump(data, fout)


def store_routes_gzip(data, filename):
    data_str = json.dumps(data)
    data_bytes = data_str.encode('utf-8')
    with gzip.open(filename, 'w') as fout:
        fout.write(data_bytes)


if __name__ == '__main__':
    cache = True
    cache_file = "routes/cache.gzip"
    config_file = None
    output_file_name = None

    if len(sys.argv) < 3:
        usage()

    config_file = str(sys.argv[1])
    output_file_name = str(sys.argv[2])
    print("Output file name will be: ", output_file_name)

    if cache:
        previous_routes = read_routes_gzip(cache_file)
    else:
        previous_routes = {}

    config_dic = load_config(config_file)
    t, s, cp = get_points()
    routes = asyncio.run(calculate_routes(t, s, cp))

    print("storing routes...")
    store_routes_json(routes, output_file_name)

    if cache and counter > 0:
        print("storing cache...")
        previous_routes = {**previous_routes, **routes}  # z = x | y # NOTE: 3.9+ ONLY
        store_routes_gzip(previous_routes, cache_file)


