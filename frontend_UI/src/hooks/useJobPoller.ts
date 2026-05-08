import { useState, useEffect, useRef, useCallback } from 'react'
import type { JobStatus } from '../types/api'

const POLL_TIMEOUT_MS = 10 * 60 * 1000

interface PollState<T> {
  status: JobStatus | null
  data: T | null
  error: string | null
  isPolling: boolean
}

// type PollerFn<T> = () => Promise<{ status: JobStatus; result?: T; error?: string }>

type PollerFn<T> = () => Promise<{
  status: JobStatus
  result?: T | null
  error?: string | null
  error_message?: string | null
}>


export function useJobPoller<T>(
  pollerFn: PollerFn<T> | null,
  intervalMs = 2000
): PollState<T> {
  const [state, setState] = useState<PollState<T>>({
    status: null,
    data: null,
    error: null,
    isPolling: false,
  })

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const mountedRef = useRef(true)
  const startTimeRef = useRef<number | null>(null)

  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (mountedRef.current) {
      setState(s => ({ ...s, isPolling: false }))
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!pollerFn) {
      stop()
      return
    }

    startTimeRef.current = Date.now()
    setState(s => ({ ...s, isPolling: true }))

    const tick = async () => {
      if (startTimeRef.current !== null && Date.now() - startTimeRef.current > POLL_TIMEOUT_MS) {
        setState(s => ({ ...s, error: 'Polling timed out after 10 minutes. Please try again.', isPolling: false }))
        stop()
        return
      }

      try {
        const res = await pollerFn()
        if (!mountedRef.current) return

        // setState(s => ({
        //   ...s,
        //   status: res.status,
        //   data: res.result ?? s.data,
        //   error: res.error ?? null,
        // }))

        setState(s => ({
          ...s,
          status: res.status,
          data: res.result ?? s.data,
          error: res.error_message ?? res.error ?? null,
          }))

        if (res.status === 'completed' || res.status === 'failed') {
          stop()
        }
      } catch (err) {
        if (!mountedRef.current) return
        const message = err instanceof Error ? err.message : 'Polling error'
        setState(s => ({ ...s, error: message, isPolling: false }))
        stop()
      }
    }

    tick()
    intervalRef.current = setInterval(tick, intervalMs)

    return stop
  }, [pollerFn, intervalMs, stop])

  return state
}
