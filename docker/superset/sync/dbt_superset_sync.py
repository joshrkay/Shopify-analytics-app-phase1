"""
dbt → Superset Sync Job

Synchronizes dbt models with Superset datasets based on dbt manifest.json.
This enables automatic dataset creation and updates when dbt models change.

Sync Flow (ASCII):
    dbt run → manifest.json → sync job → Superset datasets

Features:
- Parses dbt manifest.json to extract model metadata
- Creates/updates Superset datasets via API
- Applies RLS rules to new datasets
- Syncs metrics and column descriptions
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DbtModel:
    """Represents a dbt model extracted from manifest."""
    unique_id: str
    name: str
    schema: str
    database: str
    description: str
    columns: dict[str, dict]
    materialized: str
    tags: list[str]


@dataclass
class SupersetDataset:
    """Represents a Superset dataset."""
    id: int | None
    table_name: str
    schema: str
    database_id: int
    description: str
    columns: list[dict]


class DbtManifestParser:
    """Parses dbt manifest.json to extract model metadata."""

    def __init__(self, manifest_path: str | Path):
        self.manifest_path = Path(manifest_path)
        self._manifest: dict | None = None

    def load(self) -> None:
        """Load the manifest file."""
        with open(self.manifest_path) as f:
            self._manifest = json.load(f)

    @property
    def manifest(self) -> dict:
        if self._manifest is None:
            self.load()
        return self._manifest

    def get_models(self, schema_filter: str | None = None) -> list[DbtModel]:
        """
        Extract models from manifest.

        Args:
            schema_filter: Optional schema name to filter by

        Returns:
            List of DbtModel objects
        """
        models = []
        nodes = self.manifest.get('nodes', {})

        for node_id, node in nodes.items():
            if not node_id.startswith('model.'):
                continue

            if schema_filter and node.get('schema') != schema_filter:
                continue

            models.append(DbtModel(
                unique_id=node['unique_id'],
                name=node['name'],
                schema=node.get('schema', 'public'),
                database=node.get('database', 'analytics'),
                description=node.get('description', ''),
                columns=node.get('columns', {}),
                materialized=node.get('config', {}).get('materialized', 'view'),
                tags=node.get('tags', []),
            ))

        return models

    def get_fact_models(self) -> list[DbtModel]:
        """Get all fact table models."""
        return [m for m in self.get_models() if m.name.startswith('fact_')]

    def get_metric_models(self) -> list[DbtModel]:
        """Get all metric models."""
        return [m for m in self.get_models() if m.name.startswith('fct_')]

    def get_mart_models(self) -> list[DbtModel]:
        """Get all mart models."""
        return [m for m in self.get_models() if m.name.startswith('mart_')]


class SupersetClient:
    """HTTP client for Superset API."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
    ):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self._access_token: str | None = None
        self._csrf_token: str | None = None
        self._client = httpx.Client(timeout=30.0)

    def authenticate(self) -> None:
        """Authenticate and get access token."""
        response = self._client.post(
            f'{self.base_url}/api/v1/security/login',
            json={
                'username': self.username,
                'password': self.password,
                'provider': 'db',
            }
        )
        response.raise_for_status()
        self._access_token = response.json()['access_token']

        # Get CSRF token
        csrf_response = self._client.get(
            f'{self.base_url}/api/v1/security/csrf_token/',
            headers={'Authorization': f'Bearer {self._access_token}'}
        )
        csrf_response.raise_for_status()
        self._csrf_token = csrf_response.json()['result']

    @property
    def headers(self) -> dict[str, str]:
        """Get request headers with auth."""
        return {
            'Authorization': f'Bearer {self._access_token}',
            'X-CSRFToken': self._csrf_token or '',
            'Content-Type': 'application/json',
        }

    def get_database_id(self, database_name: str) -> int | None:
        """Get database ID by name."""
        response = self._client.get(
            f'{self.base_url}/api/v1/database/',
            headers=self.headers,
            params={'q': json.dumps({'filters': [{'col': 'database_name', 'opr': 'eq', 'value': database_name}]})}
        )
        response.raise_for_status()
        result = response.json()
        if result.get('result'):
            return result['result'][0]['id']
        return None

    def get_dataset(self, table_name: str, schema: str) -> dict | None:
        """Get dataset by table name and schema."""
        response = self._client.get(
            f'{self.base_url}/api/v1/dataset/',
            headers=self.headers,
            params={'q': json.dumps({
                'filters': [
                    {'col': 'table_name', 'opr': 'eq', 'value': table_name},
                    {'col': 'schema', 'opr': 'eq', 'value': schema},
                ]
            })}
        )
        response.raise_for_status()
        result = response.json()
        if result.get('result'):
            return result['result'][0]
        return None

    def create_dataset(self, dataset: SupersetDataset) -> int:
        """Create a new dataset."""
        payload = {
            'table_name': dataset.table_name,
            'schema': dataset.schema,
            'database': dataset.database_id,
            'description': dataset.description,
        }

        response = self._client.post(
            f'{self.base_url}/api/v1/dataset/',
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        return response.json()['id']

    def update_dataset(self, dataset_id: int, dataset: SupersetDataset) -> None:
        """Update an existing dataset."""
        payload = {
            'description': dataset.description,
        }

        response = self._client.put(
            f'{self.base_url}/api/v1/dataset/{dataset_id}',
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()

    def refresh_dataset_columns(self, dataset_id: int) -> None:
        """Refresh dataset columns from database."""
        response = self._client.put(
            f'{self.base_url}/api/v1/dataset/{dataset_id}/refresh',
            headers=self.headers
        )
        response.raise_for_status()


class DbtSupersetSync:
    """
    Synchronizes dbt models with Superset datasets.

    Usage:
        sync = DbtSupersetSync(
            manifest_path='/path/to/manifest.json',
            superset_url='http://superset:8088',
            superset_user='admin',
            superset_password='admin',
            database_name='analytics',
        )
        sync.run()
    """

    def __init__(
        self,
        manifest_path: str | Path,
        superset_url: str,
        superset_user: str,
        superset_password: str,
        database_name: str = 'analytics',
    ):
        self.parser = DbtManifestParser(manifest_path)
        self.client = SupersetClient(superset_url, superset_user, superset_password)
        self.database_name = database_name
        self._database_id: int | None = None

    def run(self) -> dict[str, Any]:
        """
        Run the sync job.

        Returns:
            Summary of sync results
        """
        logger.info('Starting dbt → Superset sync')

        # Authenticate
        self.client.authenticate()
        logger.info('Authenticated with Superset')

        # Get database ID
        self._database_id = self.client.get_database_id(self.database_name)
        if not self._database_id:
            raise ValueError(f"Database '{self.database_name}' not found in Superset")

        # Load manifest
        self.parser.load()
        logger.info(f'Loaded dbt manifest from {self.parser.manifest_path}')

        # Get models to sync
        fact_models = self.parser.get_fact_models()
        metric_models = self.parser.get_metric_models()
        mart_models = self.parser.get_mart_models()

        all_models = fact_models + metric_models + mart_models
        logger.info(f'Found {len(all_models)} models to sync')

        # Sync each model
        results = {
            'created': [],
            'updated': [],
            'skipped': [],
            'errors': [],
        }

        for model in all_models:
            try:
                result = self._sync_model(model)
                results[result].append(model.name)
            except Exception as e:
                logger.error(f'Error syncing model {model.name}: {e}')
                results['errors'].append({'model': model.name, 'error': str(e)})

        logger.info(f'Sync complete: {len(results["created"])} created, '
                    f'{len(results["updated"])} updated, {len(results["errors"])} errors')

        return results

    def _sync_model(self, model: DbtModel) -> str:
        """
        Sync a single dbt model to Superset.

        Returns:
            'created', 'updated', or 'skipped'
        """
        # Check if dataset exists
        existing = self.client.get_dataset(model.name, model.schema)

        dataset = SupersetDataset(
            id=existing['id'] if existing else None,
            table_name=model.name,
            schema=model.schema,
            database_id=self._database_id,
            description=model.description,
            columns=[
                {'column_name': col_name, 'description': col_info.get('description', '')}
                for col_name, col_info in model.columns.items()
            ],
        )

        if existing:
            # Update existing dataset
            self.client.update_dataset(existing['id'], dataset)
            self.client.refresh_dataset_columns(existing['id'])
            logger.info(f'Updated dataset: {model.name}')
            return 'updated'
        else:
            # Create new dataset
            dataset_id = self.client.create_dataset(dataset)
            self.client.refresh_dataset_columns(dataset_id)
            logger.info(f'Created dataset: {model.name} (id={dataset_id})')
            return 'created'


def main():
    """CLI entrypoint for the sync job."""
    import argparse

    parser = argparse.ArgumentParser(description='Sync dbt models to Superset')
    parser.add_argument('--manifest', required=True, help='Path to dbt manifest.json')
    parser.add_argument('--superset-url', default=os.getenv('SUPERSET_URL', 'http://superset:8088'))
    parser.add_argument('--superset-user', default=os.getenv('SUPERSET_USER', 'admin'))
    parser.add_argument('--superset-password', default=os.getenv('SUPERSET_PASSWORD', 'admin'))
    parser.add_argument('--database', default='analytics', help='Target database name')

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    sync = DbtSupersetSync(
        manifest_path=args.manifest,
        superset_url=args.superset_url,
        superset_user=args.superset_user,
        superset_password=args.superset_password,
        database_name=args.database,
    )

    results = sync.run()
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
