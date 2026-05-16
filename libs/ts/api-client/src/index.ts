// Placeholder — real client generated from OpenAPI in Phase 1
// After: nx run api:openapi && nx run api-client:generate

export type ApiClient = {
  baseUrl: string;
};

export function createApiClient(baseUrl = "/api"): ApiClient {
  return { baseUrl };
}

export const apiClient = createApiClient();
