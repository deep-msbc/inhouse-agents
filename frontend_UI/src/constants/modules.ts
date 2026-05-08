import type { TreeNode } from '../types/api'

export const SAMPLE_MODULES = [
  'production_process_master',
  'job_production_tracking',
  'machine_telemetry',
  'operator_assignment',
  'quality_inspection',
]

export const FRONTEND_MODULES = [
  'ProductionProcess',
  'JobTracking',
  'MachineTelemetry',
  'OperatorAssignment',
  'QualityInspection',
]

export const MOCK_STATS = {
  modules: 5,
  userStories: 17,
  entityDiagrams: 4,
}

/* ─── Frontend tree (~/web) ─── */
const makeFeModule = (name: string, hookName: string, extra: TreeNode[] = []): TreeNode => ({
  type: 'folder', name, path: `web/${name}`,
  children: [
    {
      type: 'folder', name: 'pages', path: `web/${name}/pages`,
      children: [{ type: 'file', name: `${name}Page.tsx`, path: `web/${name}/pages/${name}Page.tsx` }],
    },
    {
      type: 'folder', name: 'config', path: `web/${name}/config`, tag: 'config',
      children: [{ type: 'file', name: 'dashboardConfig.ts', path: `web/${name}/config/dashboardConfig.ts`, tag: 'config' }],
    },
    {
      type: 'folder', name: 'services', path: `web/${name}/services`,
      children: [{ type: 'file', name: `${hookName}.ts`, path: `web/${name}/services/${hookName}.ts` }],
    },
    { type: 'file', name: 'routes.ts', path: `web/${name}/routes.ts`, tag: 'routing' },
    { type: 'file', name: 'dataflow.md', path: `web/${name}/dataflow.md`, tag: 'flow' },
    ...extra,
  ],
})

export const FE_TREE: TreeNode[] = [
  { type: 'file', name: 'dataflow.md', path: 'web/dataflow.md', tag: 'flow' },
  makeFeModule('MachineTelemetry', 'useMachineTelemetry'),
  makeFeModule('OperatorAssignment', 'useOperatorAssignment'),
  makeFeModule('QualityInspection', 'useQualityInspection'),
  makeFeModule('ProductionProcess', 'useProductionProcess'),
  makeFeModule('JobTracking', 'useJobTracking'),
]

/* ─── Backend tree (~/api) ─── */
const makeBeModule = (name: string): TreeNode => ({
  type: 'folder', name, path: `api/${name}`,
  children: [
    { type: 'file', name: 'models.py', path: `api/${name}/models.py` },
    { type: 'file', name: 'serializers.py', path: `api/${name}/serializers.py` },
    { type: 'file', name: 'views.py', path: `api/${name}/views.py` },
    { type: 'file', name: 'urls.py', path: `api/${name}/urls.py` },
    { type: 'file', name: 'admin.py', path: `api/${name}/admin.py` },
    { type: 'file', name: 'apps.py', path: `api/${name}/apps.py` },
    { type: 'file', name: 'api.py', path: `api/${name}/api.py`, tag: 'api' },
  ],
})

export const BE_TREE: TreeNode[] = [
  makeBeModule('machine_telemetry'),
  makeBeModule('operator_assignment'),
  makeBeModule('quality_inspection'),
  makeBeModule('production_process_master'),
  makeBeModule('job_production_tracking'),
  {
    type: 'folder', name: 'auth', path: 'api/auth', tag: 'auth',
    children: [
      { type: 'file', name: 'models.py', path: 'api/auth/models.py' },
      { type: 'file', name: 'views.py', path: 'api/auth/views.py' },
      { type: 'file', name: 'urls.py', path: 'api/auth/urls.py' },
      { type: 'file', name: 'serializers.py', path: 'api/auth/serializers.py' },
    ],
  },
]

/* ─── Full stack tree (~/workspace) ─── */
export const FS_TREE: TreeNode[] = [
  ...BE_TREE,
  ...FE_TREE.map(n => ({ ...n, path: `workspace/web/${n.name}` })),
]

export const FILE_COUNTS: Record<string, number> = {
  frontend: 25,
  backend: 44,
  fullstack: 69,
}

export const TREE_ROOTS: Record<string, string> = {
  frontend: '~/web',
  backend: '~/api',
  fullstack: '~/workspace',
}

export const STACK_LABELS: Record<string, string> = {
  frontend: 'Frontend',
  backend: 'Backend',
  fullstack: 'Backend + Frontend',
}

export const MODULE_COUNTS: Record<string, number[]> = {
  production_process_master: [4],
  job_production_tracking: [5],
  machine_telemetry: [6],
  operator_assignment: [4],
  quality_inspection: [5],
}
