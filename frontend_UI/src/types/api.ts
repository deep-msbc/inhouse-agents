export type JobStatus = 'pending' | 'processing' | 'completed' | 'failed'

export interface Job {
  id: string
  status: JobStatus
  created_at: string
}

// export interface JobStatusResponse<T = unknown> {
//   job_id: string
//   status: JobStatus
//   result?: T
//   error?: string
// }

export interface JobStatusResponse<T = unknown> {
  job_id: string
  job_type?: string
  status: JobStatus
  result?: T | null
  error?: string | null
  error_message?: string | null
  created_at?: string | null
  updated_at?: string | null
}



// export interface ExtractionOutput {
//   job_id: string
//   modules: string[]
//   user_stories?: number
//   entity_diagrams?: number
// }

export interface ExtractionOutput {
  status: string
  mode: 'frontend' | 'backend' | 'both'
  filename: string
  extraction_id?: string
  extraction: Record<string, unknown>
  graph?: Record<string, unknown>
  usage?: Record<string, unknown>
}


export interface PlanOutput {
  job_id: string
  plan: Record<string, unknown>
}

// export interface JobSubmitResponse {
//   job_id: string
//   status: JobStatus
// }

export interface JobSubmitResponse {
  job_id: string
  status: JobStatus | string
  message?: string
}


export type TreeNodeType = 'folder' | 'file'

export interface TreeNode {
  type: TreeNodeType
  name: string
  path: string
  tag?: string
  children?: TreeNode[]
}

export type ExtractionMode = 'frontend' | 'backend' | 'fullstack'

export interface FeFlags {
  components: boolean
  routing: boolean
  flow: boolean
  config: boolean
}

export interface ApiError {
  message: string
  status?: number
}

// Auth
export interface LoginRequest {
  email: string
  password: string
}

export interface SignupRequest {
  name: string
  email: string
  password: string
}

export interface AuthResponse {
  token: string
  user: {
    email: string
    name: string
  }
}

// Upload
export interface UploadResponse {
  upload_id: string
  filename: string
  status: string
}

// Job polling with progress
export interface JobPollResponse {
  job_id: string
  status: JobStatus
  progress?: number
  stage?: string
  message?: string
  file_tree?: TreeNode[]
  files?: GeneratedFile[]
  download_url?: string
}

export interface GeneratedFile {
  path: string
  content: string
}

export interface BackendGeneratorRequest {
  extraction_id: string
  output_path: string
  backend_action: string
}

export interface BackendGenerationResult {
  project_name: string
  generated_apps: string[]
  generated_files: GeneratedFile[]
  success: boolean
  errors: string[]
}

export interface BackendGenerationOutput {
  job_id: string
  status: JobStatus
  result: BackendGenerationResult
}
