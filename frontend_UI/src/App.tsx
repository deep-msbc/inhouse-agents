// import { useState } from 'react'
// import { Generator } from './pages/Generator'
// import { LoginPage } from './pages/LoginPage'

// export default function App() {
//   const [token, setToken] = useState<string | null>(
//     localStorage.getItem('auth_token')
//   )
//   const [userName, setUserName] = useState<string>(
//     localStorage.getItem('auth_user') ?? 'AK'
//   )

//   function handleAuth(newToken: string, name: string) {
//     setToken(newToken)
//     setUserName(name)
//   }

//   function handleLogout() {
//     localStorage.removeItem('auth_token')
//     localStorage.removeItem('auth_user')
//     setToken(null)
//   }

//   if (!token) {
//     return <LoginPage onAuth={handleAuth} />
//   }

//   return <Generator userName={userName} onLogout={handleLogout} />
// }


import { useState } from 'react'
import { Generator } from './pages/Generator'
import { LoginPage } from './pages/LoginPage'

export default function App() {
  const [token, setToken] = useState<string | null>(
    localStorage.getItem('auth_token')
  )

  const [userName, setUserName] = useState<string>(
    localStorage.getItem('auth_user') ?? 'Demo User'
  )

  function handleAuth(newToken: string, name: string) {
    localStorage.setItem('auth_token', newToken)
    localStorage.setItem('auth_user', name)

    setToken(newToken)
    setUserName(name)
  }

  function handleLogout() {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    setToken(null)
    setUserName('Demo User')
  }

  if (!token) {
    return <LoginPage onAuth={handleAuth} />
  }

  return <Generator userName={userName} onLogout={handleLogout} />
}