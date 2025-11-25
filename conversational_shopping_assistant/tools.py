import os
from functools import lru_cache
from google.cloud import discoveryengine_v1 as discoveryengine
from google import genai
from google.api_core.client_options import ClientOptions
from typing import Optional, Dict, Any, List
from proto.marshal.collections.repeated import RepeatedComposite


# Retrieve datastore IDs from environment variables. These are unique identifiers for your search indexes.
ITEM_DATA_STORE_ID = os.getenv("ITEM_DATA_STORE_ID")
REVIEW_DATA_STORE_ID = os.getenv("REVIEW_DATA_STORE_ID")

# Creates an asynchronous client for the Discovery Engine Search Service.
def _get_search_async_client(location: str = "global"):
    # Configure the API endpoint based on the specified location (e.g., 'us', 'eu').
    client_options = None if location == "global" else ClientOptions(
       api_endpoint=f"{location}-discoveryengine.googleapis.com"
    )
    return discoveryengine.SearchServiceAsyncClient(client_options=client_options)

# Recursively converts Protobuf-like objects (e.g., from API responses) into native Python dictionaries and lists.
def _convert_to_native(obj):
    if hasattr(obj, 'items'):
        return {k: _convert_to_native(v) for k, v in obj.items()}
    elif isinstance(obj, (list, RepeatedComposite)):
        return [_convert_to_native(e) for e in obj]
    else:
        return obj

# Retrieves and caches Google Cloud project configuration from environment variables.
@lru_cache(maxsize=1)
def _get_config() -> Dict[str, str]:
    return {
        "PROJECT_ID": os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
        "LOCATION": (os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip() or "global"),
    }

# Helper function to combine a list of filter conditions into a single string for the API call.
def _build_filter_string(filters: list) -> Optional[str]:
    """Helper function to combine a list of filter conditions into a single string."""
    if not filters:
        return None
    return " AND ".join(filters)


# Core function to execute a search query against a specified Discovery Engine data store.
async def _execute_search(data_store_id: str, query: str, filter_string: Optional[str], max_results: int = 10) -> Dict[str, Any]:
    """Helper function to execute the Discovery Engine API call asynchronously."""
    try:
        # ---- Validate input ----
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")

        cfg = _get_config()
        project_id = cfg.get("PROJECT_ID")
        location = cfg.get("LOCATION", "global")
        
        if not project_id:
            raise ValueError("Missing required environment variable: PROJECT_ID")
        if location not in {"global", "us", "eu"}:
            raise ValueError("LOCATION must be one of: 'global', 'us', 'eu'")

        client = _get_search_async_client()

        # ---- Data-store scoped serving config (no blending) ----
        # Construct the full resource path for the serving configuration.
        serving_config = (
            f"projects/{project_id}/locations/{location}"
            f"/collections/default_collection/dataStores/{data_store_id}"
            f"/servingConfigs/default_serving_config"
        )

        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query,
            page_size=max_results,
            filter=filter_string,
        )
        # Asynchronously call the search service.
        response = await client.search(request=request)
        
        search_results = []
        for result in response.results:
            # Convert the document data from Protobuf struct to a native Python dictionary.
            search_results.append(_convert_to_native(result.document.struct_data))

        report = "Search completed successfully."

        return {
            "status": "success",
            "report": report,
            "data": {
                "data_store_id": data_store_id,
                "search_results": search_results,
            },
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "report": "An unexpected error occurred while answering the question.",
        }


# --- Function Tool 1: Item Metadata Datastore ---

# Searches for items in the metadata datastore with various filter options.
async def search_items_with_filters(
    query: str, 
    min_avg_rating: Optional[float] = None, 
    max_avg_rating: Optional[float] = None, 
    min_rating_number: Optional[int] = None,
    max_price: Optional[float] = None,
    parent_asin: Optional[str] = None,
) -> dict[str, Any]:
    """
    Searches the Item Metadata datastore using filters on price, average rating, and rating count.

    Args:
        query (str): The natural language search query.
        min_avg_rating (float): Minimum average rating (e.g., 4.0).
        max_avg_rating (float): Maximum average rating (e.g., 4.5).
        min_rating_number (int): Minimum number of ratings (e.g., 100) using a greater than or equal to comparison.
        max_price (float): Maximum price (e.g., 50.00).
        parent_asin (str): The parent ASIN identifier for a product to find a specific item.

    Returns:
        A dictionary containing the search results.
        {
          'status': 'success' | 'error',
          'report': 'Human-readable message',
          'data': {
              'search_results': list[dict]
          }
        }
    """
    # Build a list of filter expressions based on the provided arguments.
    filters = []

    if min_avg_rating is not None:
        filters.append(f"average_rating >= {min_avg_rating}")
    if max_avg_rating is not None:
        filters.append(f"average_rating <= {max_avg_rating}")
    if min_rating_number is not None:
        filters.append(f"rating_number >= {min_rating_number}")
    if max_price is not None:
        filters.append(f"price <= {max_price}")
    if parent_asin is not None:
        filters.append(f'parent_asin: "{parent_asin}"')

    # Combine filters and execute the search on the item data store.
    filter_string = _build_filter_string(filters)
    return await _execute_search(ITEM_DATA_STORE_ID, query, filter_string)



# --- Function Tool 2: Reviews Metadata Datastore ---

# Searches for product reviews in the reviews datastore with various filter options.
async def search_reviews_with_filters(
    query: str, 
    min_rating: Optional[float] = None, 
    max_rating: Optional[float] = None, 
    min_helpful_votes: Optional[int] = None,
    parent_asin: Optional[str] = None
) -> dict[str, Any]:
    """
    Searches the Reviews Metadata datastore using filters on rating, helpful votes, and parent ASIN.

    Args:
        query (str): The natural language search query.
        min_rating (float): Minimum rating for the review (e.g., 4.0).
        max_rating (float): Maximum rating for the review (e.g., 5.0).
        min_helpful_votes (int): Minimum number of helpful votes (e.g., 5).
        parent_asin (str): Optional filter to view reviews for a specific product using its
          parent ASIN.

    Returns:
        A dictionary containing the search results.
        {
          'status': 'success' | 'error',
          'report': 'Human-readable message',
          'data': {
              'search_results': list[dict]
          }
        }
    """
    # Build a list of filter expressions for reviews.
    filters = []

    if min_rating is not None:
        filters.append(f"rating >= {min_rating}")
    if max_rating is not None:
        filters.append(f"rating <= {max_rating}")
    if min_helpful_votes is not None:
        filters.append(f"helpful_vote >= {min_helpful_votes}")
    if parent_asin is not None:
        filters.append(f'parent_asin: "{parent_asin}"')

    # Combine filters and execute the search on the review data store.
    filter_string = _build_filter_string(filters)
    return await _execute_search(REVIEW_DATA_STORE_ID, query, filter_string)

# --- Function Tool 3: Summarize Reviews ---
# Summarizes a list of review texts using a generative model.
async def summarize_reviews(reviews: List[str]) -> Dict[str, Any]:
    """
    Summarizes a list of product reviews.

    Args:
        reviews: A list of review texts.

    Returns:
        {
          'status': 'success' | 'error',
          'report': 'Human-readable message',
          'data': {
        'summary': str, # The generated summary of reviews.
        'review_count': int # The number of reviews summarized.
          }
        }
    """
    # Handle the case where no reviews are provided.
    if not reviews:
        report = "No reviews provided to summarize."
        return {
            "status": "success",
            "report": report,
            "data": {"summary": report, "review_count": 0},
        }

    review_count = len(reviews)
    report = f"Successfully summarized {review_count} reviews."

    # Initialize the Generative AI client.
    client = genai.Client()
    MODEL_ID = "gemini-2.5-flash"
    # Create a detailed prompt for the language model to generate a structured summary.
    prompt = f"""
                I will provide you with a list of customer reviews for a product.
                Your task is to generate a concise summary of these reviews.
                The summary should highlight:
                1.  Common positive aspects (pros).
                2.  Common negative aspects (cons).
                3.  An overall sentiment or recommendation.
                
                Start your summary by stating the number of reviews considered, for example: "Based on 10 reviews, here is a summary:".
                Please format your response clearly with headings for "Positive Highlights", "Negative Aspects", and "Overall Summary".

                Here are the reviews:
                {'- ' + '\n- '.join(reviews)}
                """

    try:
        # Call the generative model to get the summary.
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt
        )
        return {
            "status": "success",
            "report": report,
            "data": {"summary": response.text, "review_count": review_count},
        }
    except ValueError as e:
        return {
            "status": "error",
            "error": f"Invalid input for summarization: {str(e)}",
            "report": "Summarization failed due to invalid review content.",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "report": "An unexpected error occurred during review summarization.",
        }