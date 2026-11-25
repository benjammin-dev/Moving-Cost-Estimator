import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import Login from "./pages/Login"
import Register from "./pages/Register"
import NotFound from "./pages/NotFound"
import ProtectedRoute from "./components/ProtectedRoute"
import Estimate from "./pages/Estimate"
import { ACCESS_TOKEN, REFRESH_TOKEN } from "./constants"
import CompletedMoves from "./pages/CompletedMoves"
import QuoteWidget from "./pages/QuoteWidget"
import Movers from "./pages/Movers"
import MoverDetail from "./pages/MoverDetail"
import AddMover from "./pages/AddMover"

// Only clear login tokens, so other saved preferences (like the theme) stay.
function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN)
  localStorage.removeItem(REFRESH_TOKEN)
}

function Logout() {
  clearTokens()
  return <Navigate to="/login" />
}

function RegisterAndLogout() {
  clearTokens()
  return <Register />
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Estimate />
            </ProtectedRoute>
          }
        />
        <Route
          path="/completed"
          element={
            <ProtectedRoute>
              <CompletedMoves />
            </ProtectedRoute>
          }
        />
        {/* Staff only: the pages show a notice to other accounts */}
        <Route
          path="/movers"
          element={
            <ProtectedRoute>
              <Movers />
            </ProtectedRoute>
          }
        />
        <Route
          path="/movers/new"
          element={
            <ProtectedRoute>
              <AddMover />
            </ProtectedRoute>
          }
        />
        <Route
          path="/movers/:id"
          element={
            <ProtectedRoute>
              <MoverDetail />
            </ProtectedRoute>
          }
        />
        {/* Public, no login: embeddable quote widget */}
        <Route path="/widget" element={<QuoteWidget />} />
        <Route path="/login" element={<Login />} />
        <Route path="/logout" element={<Logout />} />
        <Route path="/register" element={<RegisterAndLogout />} />
        <Route path="*" element={<NotFound />}></Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
