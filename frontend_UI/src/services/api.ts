import axios from 'axios'
import type {
  JobStatusResponse, ExtractionOutput, PlanOutput, JobSubmitResponse,
  AuthResponse, LoginRequest, SignupRequest, UploadResponse, JobPollResponse,
  BackendGeneratorRequest, BackendGenerationResult,
} from '../types/api'

const client = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Attach token to every request if present
client.interceptors.request.use(config => {
  const token = localStorage.getItem('auth_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// /* ─── Auth ─── */
// export async function login(data: LoginRequest): Promise<AuthResponse> {
//   const res = await client.post<AuthResponse>('/auth/login', data)
//   return res.data
// }

// export async function signup(data: SignupRequest): Promise<AuthResponse> {
//   const res = await client.post<AuthResponse>('/auth/signup', data)
//   return res.data
// }

/* ─── Auth ─── */
/* TEMP DEMO AUTH: no backend call */

export async function login(data: LoginRequest): Promise<AuthResponse> {
  return {
    token: 'demo-token',
    user: {
      name: data.email.split('@')[0] || 'Demo User',
      email: data.email,
    },
  }
}

export async function signup(data: SignupRequest): Promise<AuthResponse> {
  return {
    token: 'demo-token',
    user: {
      name: data.name || data.email.split('@')[0] || 'Demo User',
      email: data.email,
    },
  }
}

/* ─── Upload ─── */
export async function uploadFile(file: File, mode: string): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)
  const res = await client.post<UploadResponse>('/uploads', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

/* ─── Generate ─── */
export async function generateCode(uploadId: string, mode: string): Promise<JobSubmitResponse> {
  const res = await client.post<JobSubmitResponse>('/requirement-extractor/parse', {
    upload_id: uploadId,
    mode,
  })
  return res.data
}

/* ─── Poll job ─── */
export async function pollJob(jobId: string): Promise<JobPollResponse> {
  const res = await client.get<JobPollResponse>(`/requirement-extractor/jobs/${jobId}`)
  return res.data
}

/* ─── Keep existing functions for backward compat ─── */
// export async function uploadDocument(file: File): Promise<JobSubmitResponse> {
//   const form = new FormData()
//   form.append('file', file)
//   const res = await client.post<JobSubmitResponse>('/requirement-extractor/parse', form, {
//     headers: { 'Content-Type': 'multipart/form-data' },
//   })
//   return res.data
// }


export async function uploadDocument(
  file: File,
  mode: 'frontend' | 'backend' | 'both' = 'both'
): Promise<JobSubmitResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)

  const res = await client.post<JobSubmitResponse>(
    '/requirement-extractor/parse',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
    }
  )

  return res.data
}

export async function getExtractionJob(jobId: string): Promise<JobStatusResponse<ExtractionOutput>> {
  const res = await client.get<JobStatusResponse<ExtractionOutput>>(
    `/requirement-extractor/jobs/${jobId}`
  )
  return res.data
}

export async function startFrontendPlan(extractionId: string): Promise<JobSubmitResponse> {
  const res = await client.post<JobSubmitResponse>('/frontend-planner/plan', {
    extraction_id: extractionId,
  })
  return res.data
}

export async function getFrontendPlanJob(jobId: string): Promise<JobStatusResponse<PlanOutput>> {
  const res = await client.get<JobStatusResponse<PlanOutput>>(
    `/frontend-planner/jobs/${jobId}`
  )
  return res.data
}

export async function startBackendGeneration(req: BackendGeneratorRequest): Promise<JobSubmitResponse> {
  const res = await client.post<JobSubmitResponse>('/backend-generator/generate', req)
  return res.data
}

export async function getBackendGenerationJob(jobId: string): Promise<JobStatusResponse<BackendGenerationResult>> {
  const res = await client.get<JobStatusResponse<BackendGenerationResult>>(
    `/backend-generator/jobs/${jobId}`
  )
  return res.data
}
