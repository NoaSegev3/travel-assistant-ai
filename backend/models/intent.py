# Role: Central enum of supported intents. Keeps the system consistent across:
# classifier output, validation rules, decision routing, response generation, and tools.

from enum import Enum


class Intent(str, Enum):
    ITINERARY_PLANNING = "itinerary_planning"
    ATTRACTIONS_RECOMMENDATIONS = "attractions_recommendations"
    PACKING_LIST = "packing_list"
    WEATHER_QUERY = "weather_query"
    CURRENCY_CONVERSION = "currency_conversion"
    CONSTRAINTS_UPDATE = "constraints_update"
    CLARIFICATION_NEEDED = "clarification_needed"
    OUT_OF_SCOPE = "out_of_scope"
