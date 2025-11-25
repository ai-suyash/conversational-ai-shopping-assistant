import asyncio
import os
import json
from typing import Any, Dict, Optional
from google.cloud import bigquery



from google.adk.agents import Agent
from google.adk.tools.tool_context import ToolContext
from google.adk.tools import BaseTool
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.bigquery import BigQueryCredentialsConfig
from google.adk.tools.bigquery import BigQueryToolset
from google.adk.tools.bigquery.config import BigQueryToolConfig
from google.adk.tools.bigquery.config import WriteMode
from google.genai import types
from .prompt import BIGQUERY_AGENT_INSTRUCTION_TEMPLATE
import google.auth


# Define a user-agent string to identify the application in API requests, which is a good practice for logging and monitoring.
USER_AGENT = "adk-agent/0.0.1"
database_settings = None

# Define a tool configuration to block write operations (making it read-only) and to pass the user-agent string.
tool_config = BigQueryToolConfig(write_mode=WriteMode.BLOCKED, application_name=USER_AGENT)

# Uses externally-managed Application Default Credentials (ADC) by default.
# This decouples authentication from the agent / tool lifecycle.
# https://cloud.google.com/docs/authentication/provide-credentials-adc
application_default_credentials, project_id = google.auth.default()
credentials_config = BigQueryCredentialsConfig(
    credentials=application_default_credentials
)

# Specify that the agent should only use the 'execute_sql' tool from the BigQuery toolset.
ADK_BUILTIN_BQ_EXECUTE_SQL_TOOL = "execute_sql"
bigquery_tool_filter = [ADK_BUILTIN_BQ_EXECUTE_SQL_TOOL]

# Instantiate a BigQuery toolset
bigquery_toolset = BigQueryToolset(
    credentials_config=credentials_config,
    bigquery_tool_config=tool_config, 
    tool_filter=bigquery_tool_filter, 
)



# Helper function to retrieve environment variables with an optional default value.
def get_env_var(key: str, default: str | None = None) -> str:
    """Get an environment variable."""
    value = os.environ.get(key)
    if value is None:
        if default is None:
            raise ValueError(f"Required environment variable {key} is not set.")
        return default
    return value

# Helper function to correctly format Python values for inclusion in a SQL query string.
def _serialize_value_for_sql(value):
    """Serialize a value for SQL."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return f"'{str(value)}'"

# Dynamically retrieves the schema and sample rows for tables in the specified BigQuery dataset.
def get_bigquery_schema_and_samples():
    """Retrieves schema and sample values for the BigQuery dataset tables."""
    
    data_project = get_env_var("BQ_DATA_PROJECT_ID", "test-project-457116")
    dataset_id = get_env_var("BQ_DATASET_ID", "poc_data")
    
    credentials, compute_project = google.auth.default()

    client = bigquery.Client(
        project=compute_project,
        credentials=credentials,
    )
    dataset_ref = bigquery.DatasetReference(data_project, dataset_id)
    tables_context = {}
    try:
        # Iterate through each table in the dataset to fetch its schema and sample data.
        for table in client.list_tables(dataset_ref):
            table_info = client.get_table(
                bigquery.TableReference(dataset_ref, table.table_id)
            )
            table_schema = [
                (schema_field.name, schema_field.field_type)
                for schema_field in table_info.schema
            ]
            table_ref = dataset_ref.table(table.table_id)
            sample_values = []
            try:
                # Fetch a small sample of rows to provide context to the language model.
                sample_query = f"SELECT * FROM `{table_ref}` LIMIT 5"
                sample_values = (
                    client.query(sample_query).to_dataframe().to_dict(orient="list")
                )
                for key in sample_values:
                    sample_values[key] = [
                        _serialize_value_for_sql(v) for v in sample_values[key]
                    ]
            except Exception as e:
                print(f"Could not get sample values for table {table_ref}: {e}")

            tables_context[str(table_ref)] = {
                "table_schema": table_schema,
                "example_values": sample_values,
            }
    except Exception as e:
        print(f"Could not list tables for dataset {dataset_ref}: {e}")


    return tables_context

# Caches the database settings to avoid refetching the schema on every invocation.
def get_database_settings():
    """Get database settings."""
    global database_settings
    if database_settings is None:
        database_settings = update_database_settings()
    return database_settings


# Fetches the latest schema and updates the global settings variable.
def update_database_settings():
    """Update database settings."""
    global database_settings
    schema = get_bigquery_schema_and_samples()
    database_settings = {
        "data_project_id": get_env_var("BQ_DATA_PROJECT_ID", "test-project-457116"),
        "dataset_id": get_env_var("BQ_DATASET_ID", "poc_data"),
        "schema": schema,
    }
    return database_settings


# A callback function executed after a tool runs, used to store results in the agent's context.
def store_results_in_context(
    tool: BaseTool,
    args: Dict[str, Any],
    tool_context: ToolContext,
    tool_response: Dict,
) -> Optional[Dict]:

    # If the SQL execution was successful, store the resulting rows in the agent's state.
    # This allows the agent to use the query results in subsequent reasoning steps.
    if tool.name == ADK_BUILTIN_BQ_EXECUTE_SQL_TOOL:
        if tool_response["status"] == "SUCCESS":
            tool_context.state["bigquery_query_result"] = tool_response["rows"]

    return None

# Get the database schema and inject it into the agent's instruction prompt.
db_settings = get_database_settings()
db_schema_str = json.dumps(db_settings, indent=2)

instruction = BIGQUERY_AGENT_INSTRUCTION_TEMPLATE.format(db_schema_str=db_schema_str)

# Agent Definition
root_agent = Agent(
    model='gemini-2.5-flash',
    name='query_agent',
    description=(
        "Agent to answer questions about BigQuery data and models and execute"
        " SQL queries."
    ),
    instruction=instruction,
    tools=[bigquery_toolset],
    after_tool_callback=store_results_in_context,
)
