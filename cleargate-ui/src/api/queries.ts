import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, setApiAuthToken } from './client';
import { useAuth } from '../app/AuthContext';
import { JobDetail } from './schemas';
import { isTerminalState } from '../domain/states';
import { useEffect } from 'react';

export function useSyncAuthToken() {
  const { token } = useAuth();
  useEffect(() => {
    setApiAuthToken(token);
  }, [token]);
}

// Health query
export function useHealthQuery() {
  useSyncAuthToken();
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api.getHealth(),
    staleTime: 30000,
    retry: 1,
  });
}

// Job detail with smart polling
export function useJobQuery(jobId: string | undefined) {
  useSyncAuthToken();
  return useQuery<JobDetail, Error>({
    queryKey: ['job', jobId],
    queryFn: () => {
      if (!jobId) throw new Error('Missing job ID');
      return api.getJob(jobId);
    },
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      // Stop polling on terminal states or REVIEW_REQUIRED per Section 5.3
      if (!state || isTerminalState(state) || state === 'REVIEW_REQUIRED') {
        return false;
      }
      // Poll every 3 seconds while RECEIVED or PROCESSING
      return 3000;
    },
    refetchIntervalInBackground: false, // Pause when tab is hidden
    refetchOnWindowFocus: true,
  });
}

// Findings query (Reviewer role only)
export function useFindingsQuery(jobId: string | undefined, includeText = false) {
  useSyncAuthToken();
  return useQuery({
    queryKey: ['findings', jobId, includeText],
    queryFn: () => {
      if (!jobId) throw new Error('Missing job ID');
      return api.getFindings(jobId, includeText);
    },
    enabled: Boolean(jobId),
    staleTime: 5000,
  });
}

// Review items query
export function useReviewItemsQuery(jobId: string | undefined) {
  useSyncAuthToken();
  return useQuery({
    queryKey: ['review-items', jobId],
    queryFn: () => {
      if (!jobId) throw new Error('Missing job ID');
      return api.getReviewItems(jobId);
    },
    enabled: Boolean(jobId),
    staleTime: 5000,
    gcTime: 0, // Cleared immediately on unmount per Section 5.5
  });
}

// Report Markdown query
export function useReportMdQuery(jobId: string | undefined) {
  useSyncAuthToken();
  return useQuery({
    queryKey: ['report-md', jobId],
    queryFn: () => {
      if (!jobId) throw new Error('Missing job ID');
      return api.getReportMd(jobId);
    },
    enabled: Boolean(jobId),
  });
}

// Batch creation mutation
export function useCreateBatchMutation() {
  const queryClient = useQueryClient();
  useSyncAuthToken();

  return useMutation({
    mutationFn: ({ files, policy }: { files: File[]; policy?: string }) =>
      api.createBatch(files, policy),
    onSuccess: (data) => {
      // Prime individual jobs in cache
      data.jobs.forEach((job) => {
        queryClient.invalidateQueries({ queryKey: ['job', job.job_id] });
      });
    },
  });
}
