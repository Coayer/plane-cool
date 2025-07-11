from flask import Flask, request
from FlightRadar24 import FlightRadar24API
import math

app = Flask(__name__)


def distance(x1, y1, z1, x2, y2, z2):
    return math.sqrt(math.pow(x2 - x1, 2) + math.pow(y2 - y1, 2) + math.pow(z2 - z1, 2))


def pointToCartesian(longitude, latitude, altitude):
    # Convert to radians
    longitude = math.radians(longitude)
    latitude = math.radians(latitude)

    # altitude should be in meters, convert from feet if needed
    altitude_m = altitude * 0.3048  # Convert feet to meters

    def N(phi):
        return 6378137 / math.sqrt(
            1 - 0.006694379990197619 * math.pow(math.sin(phi), 2)
        )

    x = (N(latitude) + altitude_m) * math.cos(latitude) * math.cos(longitude)
    y = (N(latitude) + altitude_m) * math.cos(latitude) * math.sin(longitude)
    z = (0.9933056200098024 * N(latitude) + altitude_m) * math.sin(latitude)

    return x, y, z


def calculate_heading_to_aircraft(user_lat, user_lon, aircraft_lat, aircraft_lon):
    # Convert to radians
    user_lat_rad = math.radians(user_lat)
    user_lon_rad = math.radians(user_lon)
    aircraft_lat_rad = math.radians(aircraft_lat)
    aircraft_lon_rad = math.radians(aircraft_lon)

    # Calculate difference in longitude
    dlon = aircraft_lon_rad - user_lon_rad

    # Calculate bearing
    y = math.sin(dlon) * math.cos(aircraft_lat_rad)
    x = math.cos(user_lat_rad) * math.sin(aircraft_lat_rad) - math.sin(
        user_lat_rad
    ) * math.cos(aircraft_lat_rad) * math.cos(dlon)

    # Get bearing in radians
    bearing_rad = math.atan2(y, x)

    # Convert to degrees and normalize to 0-360
    bearing_deg = math.degrees(bearing_rad)
    bearing_deg = (bearing_deg + 360) % 360

    return bearing_deg


def get_flight_data(flight):
    """Extract flight data from a flight object"""
    try:
        # Get detailed flight info
        fr_api = FlightRadar24API()
        flight_details = fr_api.get_flight_details(flight)
        flight.set_flight_details(flight_details)

        return {
            "source": getattr(flight, "origin_airport_name", "Unknown"),
            "destination": getattr(flight, "destination_airport_name", "Unknown"),
            "airline": getattr(flight, "airline_name", "Unknown"),
            "aircraft_type": getattr(flight, "aircraft_model", "Unknown"),
            "altitude": getattr(flight, "altitude", 0),
            "latitude": getattr(flight, "latitude", 0),
            "longitude": getattr(flight, "longitude", 0),
            "heading": getattr(flight, "heading", 0),
        }
    except Exception as e:
        return None


def get_flights_with_distances(latitude, longitude, altitude, radius_m):
    """Get flights around a location with calculated distances"""
    try:
        # Convert user location to cartesian coordinates
        user_x, user_y, user_z = pointToCartesian(longitude, latitude, altitude)

        # Initialize FlightRadar24 API
        fr_api = FlightRadar24API()

        # Get flights around the location
        bounds = fr_api.get_bounds_by_point(latitude, longitude, radius_m)
        flights = fr_api.get_flights(bounds=bounds)

        aircraft_data = []

        for flight in flights:
            flight_data = get_flight_data(flight)

            if flight_data is None:
                aircraft_data.append(
                    (float("inf"), None, f"Error processing flight {flight}")
                )
                continue

            # Convert aircraft location to cartesian coordinates
            aircraft_x, aircraft_y, aircraft_z = pointToCartesian(
                flight_data["longitude"],
                flight_data["latitude"],
                flight_data["altitude"],
            )

            # Calculate distance
            dist = distance(user_x, user_y, user_z, aircraft_x, aircraft_y, aircraft_z)

            # Calculate heading to aircraft
            heading_to_aircraft = calculate_heading_to_aircraft(
                latitude, longitude, flight_data["latitude"], flight_data["longitude"]
            )

            aircraft_data.append((dist, flight_data, heading_to_aircraft))

        return aircraft_data

    except Exception as e:
        raise Exception(f"Error fetching flight data: {str(e)}")


def validate_location_params(request):
    """Validate and extract location parameters from request"""
    try:
        longitude = float(request.args.get("longitude"))
        latitude = float(request.args.get("latitude"))
        altitude = float(request.args.get("altitude", 0))
        return longitude, latitude, altitude
    except (TypeError, ValueError):
        raise ValueError("Invalid longitude, latitude, or altitude values")


@app.route("/")
def get_aircraft():
    try:
        longitude, latitude, altitude = validate_location_params(request)

        aircraft_data = get_flights_with_distances(latitude, longitude, altitude, 20000)

        # Sort by distance (closest last)
        aircraft_data.sort(key=lambda x: x[0])

        # Format output strings
        output_strings = []
        for dist, flight_data, heading_to_aircraft in aircraft_data:
            if flight_data is None:
                output_strings.append(
                    heading_to_aircraft
                )  # This contains the error message
            else:
                dist_km = dist / 1000
                aircraft_info = f"Aircraft: {flight_data['aircraft_type']} | Airline: {flight_data['airline']} | From: {flight_data['source']} | To: {flight_data['destination']} | Altitude: {flight_data['altitude']}ft | Heading: {flight_data['heading']}° | Distance: {dist_km:.2f}km | Heading to Aircraft From My Location: {heading_to_aircraft:.0f}°"
                output_strings.append(aircraft_info)

        combined_output = "\n".join(output_strings)

        prompt = "Here is information about the aircraft near to me. Based on the following question, tell me the airline, type (for example, truncate to 777-300 ER from 777-336(ER)), departing and arriving CITIES of the SINGLE aircraft which most matches. Tell me the airport's country only if it is NOT in Western Europe or North America. You don't need to give a justification for your answer. Don't include redundant information. Here is the prompt:\n"
        return combined_output + prompt, 200, {"Content-Type": "text/plain"}

    except ValueError as e:
        return f"Error: {str(e)}", 400
    except Exception as e:
        return f"Error: {str(e)}", 500


@app.route("/closest")
def get_closest_aircraft():
    try:
        longitude, latitude, altitude = validate_location_params(request)

        aircraft_data = get_flights_with_distances(latitude, longitude, altitude, 10000)

        # Filter out errors and find closest
        valid_aircraft = [
            (dist, flight_data)
            for dist, flight_data, _ in aircraft_data
            if flight_data is not None
        ]

        if not valid_aircraft:
            return (
                "No aircraft found within 10km of your location.",
                200,
                {"Content-Type": "text/plain"},
            )

        # Sort by distance and get the closest
        valid_aircraft.sort(key=lambda x: x[0])
        closest_dist, closest_flight = valid_aircraft[0]

        # Format as a sentence
        sentence = f"{closest_flight['airline']} {closest_flight['aircraft_type']} departing from {closest_flight['source']} to {closest_flight['destination']}."

        return sentence, 200, {"Content-Type": "text/plain"}

    except ValueError as e:
        return f"Error: {str(e)}", 400
    except Exception as e:
        return f"Error: {str(e)}", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
