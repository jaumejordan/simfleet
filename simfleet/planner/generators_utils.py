import math
import time

import geopandas as gpd
import geopy.distance
import requests
import shapely
from loguru import logger
from shapely.geometry import Polygon, Point
from geopy.distance import vincenty

MIN_AUTONOMY = 2


# ------------------------------------------- AUXILIARY FUNCTIONS -------------------------------------------#

def timing(f):
    def wrap(*args, **kwargs):
        # logger.debug('Starting function {}'.format(f.__name__))
        time1 = time.time()
        ret = f(*args, **kwargs)
        time2 = time.time()
        logger.debug('%s function took %0.3f ms' % (f.__name__, (time2 - time1) * 1000.0))
        return ret

    return wrap


def isPerfectSquare(x):
    # Find floating point value of
    # square root of x.
    sr = math.sqrt(x)

    # If square root is an integer
    return ((sr - math.floor(sr)) == 0)


def number2degree(number):
    """
    convert radius into degree
    Keyword arguments:
    number -- radius
    return degree
    """
    return number * 180 / math.pi


def number2radius(number):
    """
    convert degree into radius
    Keyword arguments:
    number -- degree
    return radius
    """
    return number * math.pi / 180


def draw_circle(radius_in_meters, center_point, steps=15):
    """
    get a circle shape polygon based on centerPoint and radius
    extracted and modified from https://github.com/brandonxiang/geojson-python-utils
    """
    steps = steps if steps > 15 else 15
    center = [center_point.y, center_point.x]
    dist = (radius_in_meters / 1000) / 6371
    # convert meters to radiant
    rad_center = [number2radius(center[0]), number2radius(center[1])]
    # 15 sided circle
    poly = []
    for step in range(0, steps):
        brng = 2 * math.pi * step / steps
        lat = math.asin(math.sin(rad_center[0]) * math.cos(dist) +
                        math.cos(rad_center[0]) * math.sin(dist) * math.cos(brng))
        lng = rad_center[1] + math.atan2(math.sin(brng) * math.sin(dist)
                                         * math.cos(rad_center[0]),
                                         math.cos(dist) - math.sin(rad_center[0]) * math.sin(lat))
        poly.append([number2degree(lng), number2degree(lat)])

    return Polygon(poly)


def getValidPoint(p):
    """
    Given a shapely Point object, returns the nearest point corresponding to a street.
    Requires 'requests' package
    """

    # api-endpoint
    # URL = "http://router.project-osrm.org/nearest/v1/car/" + str(p.x) + "," + str(p.y)
    URL = "http://osrm.gti-ia.upv.es/nearest/v1/driving/" + str(p.x) + "," + str(p.y)

    # parametes of the GET given here
    num_results = 1
    num_bearings = "0,20"

    # defining a params dict for the parameters to be sent to the API
    PARAMS = {'number': str(num_results), 'bearings': num_bearings}

    # sending get request and saving the response as response object
    r = requests.get(url=URL, params=PARAMS)

    # extracting data in json format
    data = r.json()

    # extracting latitude, longitude of the first matching location
    latitude = data['waypoints'][0]['location'][0]
    longitude = data['waypoints'][0]['location'][1]

    return Point(latitude, longitude)


def getRadialAreas(borders):
    """
    Given a GeoDataFrame with a Polygon, returns a list of polygons
    dividing it in 8 parts
    """
    xmin, ymin, xmax, ymax = borders.total_bounds

    center = Point(float(borders.centroid.x), float(borders.centroid.y))
    nw = Point(xmin, ymax)
    ne = Point(xmax, ymax)
    se = Point(xmax, ymin)
    sw = Point(xmin, ymin)
    n = Point((nw.x + ne.x) / 2, nw.y)
    s = Point((sw.x + se.x) / 2, sw.y)
    e = Point(ne.x, (ne.y + se.y) / 2)
    w = Point(nw.x, (nw.y + sw.y) / 2)
    points = [center, nw, n, ne, e, se, s, sw, w]
    areas = []
    for i in range(1, len(points) - 1):
        p = Polygon([[points[0].x, points[0].y], [points[i].x, points[i].y], [points[i + 1].x, points[i + 1].y]])
        areas.append(p)
    areas.append(Polygon([[points[0].x, points[0].y],
                          [points[len(points) - 1].x, points[len(points) - 1].y],
                          [points[1].x, points[1].y]]))

    return areas
    # return gpd.GeoDataFrame(crs={'init': 'epsg:4326'},geometry=areas)


def getCircleAreas(borders, num_circles=5, within=False):
    """
    Given a GeoDataFrame with a Polygon , returns a list of polygons
    dividing it with num_circles concentric circles.

    borders: GeoDataFrame with a Polygon.

    The 'within' parameter controls how circles are defined.
    * 'True': the circles will be inside the polygon, not
    traversing its borders.
    * 'False': the circles will traverse the polygon borders but
    will be trimmed against its surface.
    """

    # Calculation of surface distances to set the circles' radius

    xmin, ymin, xmax, ymax = borders.total_bounds

    center_coord = (float(borders.centroid.x), float(borders.centroid.y))

    coordinate_1 = (xmin, ymin)
    coordinate_2 = (xmax, ymin)

    width_distance = geopy.distance.distance(coordinate_1, coordinate_2).m

    coordinate_1 = (xmin, ymin)
    coordinate_2 = (xmin, ymax)

    height_distance = geopy.distance.distance(coordinate_1, coordinate_2).m

    if (within):
        if (width_distance < height_distance):
            print("Horizontal distance is lower")
            radius = width_distance / (2 * (num_circles + 1))
        else:
            print("Vertical distance is lower")
            radius = height_distance / (2 * (num_circles + 1))
    else:
        distance = geopy.distance.distance(center_coord, coordinate_1).m
        radius = distance / (num_circles + 1)

    # Area to which the circles will be trimmed
    limit = borders.geometry[0]

    # Circle creation
    circles = []
    current_radius = radius
    for c in range(num_circles):
        circles.append(draw_circle(current_radius, Point(borders.centroid.x, borders.centroid.y)))
        current_radius += radius

    # Subtracts from each circle the one created before it, so that they do not cover the same area,
    # limiting the circle area within the borders as well
    donuts = []
    for i in range(len(circles) - 1):
        nonoverlap = (circles[i + 1].symmetric_difference(circles[i])).intersection(limit)
        # nonoverlap = circles[i + 1].symmetric_difference(circles[i])
        donuts.append(nonoverlap)
    donuts.insert(0, circles[0])

    return donuts


# to_geodataframe

def to_geodataframe(df):
    if type(df) is not gpd.GeoDataFrame:
        geometry = df['geometry'].map(shapely.wkt.loads)
    else:
        geometry = df.geometry
    df = df.drop('geometry', axis=1)
    try:
        if len(geometry) > 0 and geometry[0].centroid.x > 400:
            crs = {'init': 'epsg:25830'}
        else:
            crs = {'init': 'epsg:4326'}
    except (IndexError, KeyError):
        crs = {'init': 'epsg:4326'}
    gdf = gpd.GeoDataFrame(df, crs=crs, geometry=geometry)
    gdf = gdf.to_crs({'init': 'epsg:4326'})
    return gdf


def merge_population(poi_df, pop_df, voro_df):
    pop_with_voro = spatial_join_dataframes(pop_df, "population", voro_df)

    poi_df['population'] = 0

    group = pop_with_voro.groupby("index_right").sum()
    group["index_voro"] = group.index
    poi_df["population"] = poi_df["population"].add(group["population"], fill_value=0)

    return poi_df


def merge_traffic(poi_df, traffic_df, voro_df):
    traffic_with_voro = spatial_join_dataframes(traffic_df, "traffic", voro_df)

    poi_df['traffic'] = 0

    group = traffic_with_voro.groupby("index_right").sum()
    group["index_voro"] = group.index
    poi_df["traffic"] = poi_df["traffic"].add(group["traffic"], fill_value=0)

    return poi_df


def merge_tweets(poi_df, tweets_df, voro_df):
    tweets_with_voro = spatial_join_dataframes(tweets_df, "tweets", voro_df)

    poi_df['tweets'] = 0

    group = tweets_with_voro.groupby("index_right").sum()
    group["index_voro"] = group.index
    poi_df["tweets"] = poi_df["tweets"].add(group["tweets"], fill_value=0)

    return poi_df


def spatial_join_dataframes(df, key, voro_df):
    gdf = to_geodataframe(df)
    gdf = gdf.to_crs({'init': 'epsg:4326'})
    gdf.crs = {'init': 'epsg:4326'}
    voro_df.crs = gdf.crs
    gdf_with_voro = gpd.sjoin(gdf, voro_df, how="inner", op='intersects')

    if key:
        gdf_with_voro = gdf_with_voro[["geometry", key, "index_right"]]
    else:
        gdf_with_voro = gdf_with_voro[["geometry", "index_right"]]

    return gdf_with_voro


def distance_in_meters(coord1, coord2):
    """
    Returns the distance between two coordinates in meters.

    Args:
        coord1 (list): a coordinate (longitude, latitude)
        coord2: another coordinate (longitude, latitude)

    Returns:
        float: distance meters between the two coordinates
    """
    return vincenty(coord1, coord2).meters


def has_enough_autonomy(autonomy, dist1, dist2=0):
    travel_km = calculate_km_expense(dist1, dist2)
    if travel_km >= 30.0:
        logger.critical(f"The trip requires more autonomy than the taxi's maximum autonomy")
        exit()
    # TODO comprovar que l'agent no es quede a 0 d'autonomia
    if autonomy - travel_km <= 0:
        # logger.error(f"Taxi does not have enough autonomy; Autonomy: {autonomy}, travel_km: {travel_km}")
        return False
    return True


def calculate_km_expense(fir_distance, sec_distance=0):
    return (fir_distance + sec_distance) // 1000


def has_enough_autonomy_old(autonomy, transport_position, customer_orig, customer_dest):
    if autonomy <= MIN_AUTONOMY:
        # logger.warning("{} has not enough autonomy ({}).".format(self.agent.name, autonomy))
        return False
    travel_km = calculate_km_expense(transport_position, customer_orig, customer_dest)
    # logger.debug("Transport {} has autonomy {} when max autonomy is {}"
    #              " and needs {} for the trip".format(self.agent.name, self.agent.current_autonomy_km,
    #                                                  self.agent.max_autonomy_km, travel_km))
    if autonomy - travel_km < MIN_AUTONOMY:
        # logger.warning("{} has not enough autonomy to do travel ({} for {} km).".format(self.agent.name,
        #                                                                                 autonomy, travel_km))
        return False
    return True


def calculate_km_expense_old(origin, start, dest=None):
    fir_distance = distance_in_meters(origin, start)
    sec_distance = distance_in_meters(start, dest)
    if dest is None:
        sec_distance = 0
    return (fir_distance + sec_distance) // 1000
