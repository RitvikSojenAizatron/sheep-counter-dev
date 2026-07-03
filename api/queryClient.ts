import { QueryClient, MutationCache } from '@tanstack/react-query';
import { AxiosError } from 'axios';
import { useNotificationStore } from '../state/notificationStore';

function extractErrorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    const data = error.response?.data;
    if (data?.message) return data.message;
    if (data?.error) return data.error;
    if (error.response?.status === 403) return 'You do not have permission to perform this action.';
    if (error.response?.status === 404) return 'The requested resource was not found.';
    if (error.response?.status === 409) return 'This operation conflicts with the current state.';
    if (error.response) return `Request failed (${error.response.status})`;
    if (error.code === 'ECONNABORTED') return 'Request timed out. Please try again.';
    return 'Unable to reach the server. Check your connection.';
  }
  if (error instanceof Error) return error.message;
  return 'An unexpected error occurred.';
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
  mutationCache: new MutationCache({
    onError: (error, _variables, _onMutateResult, mutation) => {
      // Skip global notification if the mutation handles errors itself
      if (mutation.options.onError) return;

      useNotificationStore.getState().show({
        message: extractErrorMessage(error),
        severity: 'error',
      });
    },
  }),
});
