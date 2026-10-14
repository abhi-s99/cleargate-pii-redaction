import React from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { Layout } from '../components/Layout';
import { ConnectPage } from '../pages/Connect';
import { UploadPage } from '../pages/Upload';
import { BatchPage } from '../pages/Batch';
import { JobsPage } from '../pages/Jobs';

import { JobDetailPage } from '../pages/JobDetail';
import { ReviewPage } from '../pages/Review';
import { HowItWorksPage } from '../pages/HowItWorks';

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <UploadPage /> },
      { path: 'connect', element: <ConnectPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: 'batches/:batchId', element: <BatchPage /> },
      { path: 'jobs/:jobId', element: <JobDetailPage /> },
      { path: 'jobs/:jobId/review', element: <ReviewPage /> },
      { path: 'how-it-works', element: <HowItWorksPage /> },
    ],
  },
]);

export const AppRouter: React.FC = () => {
  return <RouterProvider router={router} />;
};
