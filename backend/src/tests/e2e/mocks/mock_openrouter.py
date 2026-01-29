"""
Mock OpenRouter (LLM) API server for E2E testing.

Provides deterministic AI responses for testing:
- Insight generation
- Recommendation generation
- Action proposal generation
"""

import json
import re
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass

import httpx


@dataclass
class MockLLMResponse:
    """Represents a mock LLM response."""
    content: str
    model: str = "anthropic/claude-3-sonnet"
    finish_reason: str = "stop"
    usage: Optional[Dict] = None


class MockOpenRouterServer:
    """
    Mock OpenRouter API server for deterministic AI responses.

    Returns predetermined responses based on the prompt content,
    enabling reliable testing of AI-powered features.

    Usage:
        mock = MockOpenRouterServer()

        # Use default responses
        response = mock.handle_chat_completion(request)

        # Or customize responses
        mock.set_insight_response([
            {"type": "revenue_anomaly", "severity": "high", ...}
        ])
    """

    # Default mock responses for each AI feature type

    DEFAULT_INSIGHTS = [
        {
            "type": "revenue_anomaly",
            "severity": "medium",
            "summary": "Revenue dropped 15% compared to last week",
            "supporting_metrics": {
                "current_revenue": 8500,
                "previous_revenue": 10000,
                "change_percent": -15,
            },
            "time_period": "2024-01-08 to 2024-01-15",
        },
        {
            "type": "high_performing_product",
            "severity": "low",
            "summary": "Product 'Widget Pro' is trending with 50% increase in sales",
            "supporting_metrics": {
                "product_id": "gid://shopify/Product/123456",
                "product_name": "Widget Pro",
                "sales_increase_percent": 50,
            },
        },
    ]

    DEFAULT_RECOMMENDATIONS = [
        {
            "type": "increase_ad_spend",
            "platform": "meta",
            "priority": "high",
            "reason": "ROAS is 3.2x, above target threshold of 2.5x",
            "suggested_action": "Increase Meta ad budget by 20%",
            "expected_impact": {
                "additional_revenue": 2000,
                "confidence": 0.75,
            },
        },
        {
            "type": "product_promotion",
            "platform": "email",
            "priority": "medium",
            "reason": "Widget Pro has high engagement but low conversion",
            "suggested_action": "Create targeted email campaign for Widget Pro",
            "expected_impact": {
                "conversion_lift_percent": 15,
                "confidence": 0.65,
            },
        },
    ]

    DEFAULT_ACTION_PROPOSALS = [
        {
            "action_type": "update_product_price",
            "target_entity_type": "product",
            "target_entity_id": "gid://shopify/Product/123456",
            "parameters": {
                "current_price": "24.99",
                "new_price": "29.99",
                "reason": "Competitive pricing adjustment based on market analysis",
            },
            "reversible": True,
            "estimated_impact": {
                "revenue_change_percent": 8,
                "margin_change_percent": 12,
            },
        },
    ]

    def __init__(self):
        self._insight_response: Optional[List[Dict]] = None
        self._recommendation_response: Optional[List[Dict]] = None
        self._action_proposal_response: Optional[List[Dict]] = None
        self._custom_responses: Dict[str, MockLLMResponse] = {}
        self._request_history: List[Dict] = []

    def set_insight_response(self, insights: List[Dict]) -> None:
        """Configure custom insight generation response."""
        self._insight_response = insights

    def set_recommendation_response(self, recommendations: List[Dict]) -> None:
        """Configure custom recommendation generation response."""
        self._recommendation_response = recommendations

    def set_action_proposal_response(self, proposals: List[Dict]) -> None:
        """Configure custom action proposal response."""
        self._action_proposal_response = proposals

    def set_custom_response(
        self,
        prompt_pattern: str,
        response: str,
        model: str = "anthropic/claude-3-sonnet"
    ) -> None:
        """
        Configure custom response for prompts matching a pattern.

        Args:
            prompt_pattern: Regex pattern to match against system prompt
            response: Response content to return
            model: Model name to include in response
        """
        self._custom_responses[prompt_pattern] = MockLLMResponse(
            content=response,
            model=model,
        )

    def get_request_history(self) -> List[Dict]:
        """Get history of all requests (for assertions)."""
        return self._request_history.copy()

    def clear_request_history(self) -> None:
        """Clear request history."""
        self._request_history.clear()

    def reset(self) -> None:
        """Reset all custom responses and history."""
        self._insight_response = None
        self._recommendation_response = None
        self._action_proposal_response = None
        self._custom_responses.clear()
        self._request_history.clear()

    def handle_chat_completion(self, request: Dict) -> Dict:
        """
        Handle POST /api/v1/chat/completions.

        Determines response type from system prompt and returns appropriate mock.
        """
        # Record request for later assertions
        self._request_history.append(request)

        messages = request.get("messages", [])
        system_prompt = ""
        user_prompt = ""

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
            elif msg.get("role") == "user":
                user_prompt = msg.get("content", "")

        combined_prompt = f"{system_prompt}\n{user_prompt}".lower()

        # Check for custom responses first
        for pattern, response in self._custom_responses.items():
            if re.search(pattern, combined_prompt, re.IGNORECASE):
                return self._format_response(response.content, response.model)

        # Determine response type from prompt content
        if any(kw in combined_prompt for kw in ["insight", "anomaly", "trend", "analyze"]):
            insights = self._insight_response or self.DEFAULT_INSIGHTS
            content = json.dumps({"insights": insights})
        elif any(kw in combined_prompt for kw in ["recommend", "suggestion", "optimize"]):
            recommendations = self._recommendation_response or self.DEFAULT_RECOMMENDATIONS
            content = json.dumps({"recommendations": recommendations})
        elif any(kw in combined_prompt for kw in ["action", "proposal", "execute", "change"]):
            proposals = self._action_proposal_response or self.DEFAULT_ACTION_PROPOSALS
            content = json.dumps({"proposals": proposals})
        else:
            # Generic response for unrecognized prompts
            content = json.dumps({
                "response": "Mock response for testing",
                "prompt_preview": combined_prompt[:100],
            })

        model = request.get("model", "anthropic/claude-3-sonnet")
        return self._format_response(content, model)

    def _format_response(self, content: str, model: str) -> Dict:
        """Format response in OpenRouter API format."""
        return {
            "id": "chatcmpl-mock-123",
            "object": "chat.completion",
            "created": 1700000000,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

    def handle_models_list(self) -> Dict:
        """Handle GET /api/v1/models."""
        return {
            "data": [
                {
                    "id": "anthropic/claude-3-sonnet",
                    "name": "Claude 3 Sonnet",
                    "context_length": 200000,
                },
                {
                    "id": "anthropic/claude-3-opus",
                    "name": "Claude 3 Opus",
                    "context_length": 200000,
                },
                {
                    "id": "openai/gpt-4-turbo",
                    "name": "GPT-4 Turbo",
                    "context_length": 128000,
                },
            ]
        }

    def get_mock_transport(self) -> httpx.MockTransport:
        """Create an httpx MockTransport for this mock server."""
        def handle_request(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            method = request.method

            try:
                if "/chat/completions" in path and method == "POST":
                    data = json.loads(request.content)
                    result = self.handle_chat_completion(data)
                elif "/models" in path and method == "GET":
                    result = self.handle_models_list()
                else:
                    return httpx.Response(404, json={"error": "Not found"})

                return httpx.Response(200, json=result)

            except Exception as e:
                return httpx.Response(500, json={"error": str(e)})

        return httpx.MockTransport(handle_request)


# Convenience functions for creating specific test scenarios

def create_declining_revenue_insight_response(
    decline_percent: float = 15.0,
    current_revenue: float = 8500.0,
) -> List[Dict]:
    """Create insight response for declining revenue scenario."""
    previous_revenue = current_revenue / (1 - decline_percent / 100)
    return [
        {
            "type": "revenue_anomaly",
            "severity": "high" if decline_percent > 20 else "medium",
            "summary": f"Revenue dropped {decline_percent:.0f}% compared to last week",
            "supporting_metrics": {
                "current_revenue": current_revenue,
                "previous_revenue": round(previous_revenue, 2),
                "change_percent": -decline_percent,
            },
            "recommended_actions": [
                "Review marketing campaigns for any recent changes",
                "Check for inventory or fulfillment issues",
                "Analyze customer feedback for potential product issues",
            ],
        }
    ]


def create_high_roas_recommendation_response(
    platform: str = "meta",
    current_roas: float = 3.2,
    budget_increase_percent: float = 20.0,
) -> List[Dict]:
    """Create recommendation response for high ROAS scenario."""
    return [
        {
            "type": "increase_ad_spend",
            "platform": platform,
            "priority": "high",
            "reason": f"ROAS is {current_roas}x, significantly above target threshold",
            "suggested_action": f"Increase {platform.title()} ad budget by {budget_increase_percent:.0f}%",
            "expected_impact": {
                "additional_revenue_estimate": 2000,
                "confidence_score": 0.8,
            },
            "supporting_data": {
                "current_roas": current_roas,
                "target_roas": 2.5,
                "current_spend": 5000,
                "suggested_spend": 5000 * (1 + budget_increase_percent / 100),
            },
        }
    ]
