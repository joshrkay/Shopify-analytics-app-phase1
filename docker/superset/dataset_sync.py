"""
Superset Dataset Sync Automation
Syncs dbt canonical models to Superset datasets
"""

import json
import logging
import os
from typing import Dict, List
import requests

logger = logging.getLogger(__name__)


class SupersetDatasetSync:
    def __init__(self, superset_url: str, api_token: str):
        self.superset_url = superset_url
        self.api_token = api_token
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json',
        }

    def load_dbt_manifest(self, manifest_path: str) -> Dict:
        """Load dbt manifest.json"""
        with open(manifest_path, 'r') as f:
            return json.load(f)

    def extract_superset_columns(self, dbt_manifest: Dict, model_name: str) -> List[Dict]:
        """
        Extract columns marked with superset_expose: true
        """
        node_key = f"model.shopify_analytics.{model_name}"

        if node_key not in dbt_manifest['nodes']:
            raise ValueError(f"Model {model_name} not found in manifest")

        node = dbt_manifest['nodes'][node_key]
        columns = []

        for col_name, col_config in node.get('columns', {}).items():
            meta = col_config.get('meta', {})
            if meta.get('superset_expose', False):
                columns.append({
                    'column_name': col_name,
                    'type': col_config.get('data_type', 'string'),
                    'description': col_config.get('description', ''),
                })

        return columns

    def create_dataset(self, table_name: str, db_id: int, columns: List[Dict]) -> Dict:
        """Create or update Superset dataset"""
        payload = {
            'table_name': table_name,
            'database_id': db_id,
            'schema': 'analytics',
            'columns': columns,
        }

        response = requests.post(
            f'{self.superset_url}/api/v1/datasets',
            headers=self.headers,
            json=payload
        )

        if response.status_code not in [200, 201]:
            logger.error(f"Failed to create dataset {table_name}: {response.text}")
            raise Exception(f"Dataset creation failed: {response.text}")

        return response.json()

    def sync_all_datasets(self, manifest_path: str, db_id: int, model_list: List[str]):
        """Sync all models to Superset"""
        manifest = self.load_dbt_manifest(manifest_path)

        for model_name in model_list:
            try:
                columns = self.extract_superset_columns(manifest, model_name)
                self.create_dataset(model_name, db_id, columns)
                logger.info(f"Dataset synced: {model_name}")
            except Exception as e:
                logger.error(f"Failed to sync {model_name}: {str(e)}")
                raise

    def validate_sync(self, manifest_path: str, model_list: List[str]) -> bool:
        """Validate that Superset datasets match dbt models"""
        manifest = self.load_dbt_manifest(manifest_path)

        for model_name in model_list:
            dbt_columns = self.extract_superset_columns(manifest, model_name)
            superset_dataset = self.get_dataset(model_name)

            dbt_col_names = {col['column_name'] for col in dbt_columns}
            superset_col_names = {col['column_name'] for col in superset_dataset['columns']}

            if dbt_col_names != superset_col_names:
                logger.error(f"Mismatch in {model_name}: dbt={dbt_col_names}, superset={superset_col_names}")
                return False

        return True

    def get_dataset(self, table_name: str) -> Dict:
        """Retrieve dataset from Superset"""
        response = requests.get(
            f'{self.superset_url}/api/v1/datasets?table_name={table_name}',
            headers=self.headers
        )

        if response.status_code != 200:
            raise Exception(f"Failed to retrieve dataset {table_name}")

        data = response.json()
        if data['count'] == 0:
            raise ValueError(f"Dataset {table_name} not found in Superset")

        return data['result'][0]


# Default models to sync (fact tables with superset_expose metadata)
DEFAULT_MODELS_TO_SYNC = [
    'fact_orders',
    'fact_ad_spend',
    'fact_campaign_performance',
]

# Versioned metric datasets (Story 2.3)
# Each metric version gets its own dataset; dashboards reference datasets, not formulas
VERSIONED_METRIC_MODELS = [
    'metric_roas_v1',
    'metric_roas_v2',
    'metric_roas_current',
]


# Sync job entry point
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    superset_url = os.getenv('SUPERSET_URL', 'http://localhost:8088')
    api_token = os.getenv('SUPERSET_API_TOKEN')
    manifest_path = os.getenv('DBT_MANIFEST_PATH', './target/manifest.json')
    db_id = int(os.getenv('SUPERSET_DATABASE_ID', '1'))

    if not api_token:
        logger.error("SUPERSET_API_TOKEN environment variable is required")
        exit(1)

    syncer = SupersetDatasetSync(superset_url, api_token)

    all_models = DEFAULT_MODELS_TO_SYNC + VERSIONED_METRIC_MODELS

    try:
        syncer.sync_all_datasets(manifest_path, db_id, all_models)
        is_valid = syncer.validate_sync(manifest_path, all_models)

        if is_valid:
            logger.info("All datasets synced and validated successfully")
        else:
            logger.error("Validation failed - datasets out of sync")
            exit(1)
    except Exception as e:
        logger.error(f"Sync failed: {str(e)}")
        exit(1)
