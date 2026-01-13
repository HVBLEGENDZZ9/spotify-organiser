import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { signInWithGoogle, signOut, getIdToken, onAuthChange } from './firebase';
import './App.css';

// API Configuration
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

// ============================================
// ICONS - Premium SVG Icons
// ============================================

const SpotifyIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" className="spotify-icon">
    <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
  </svg>
);

const GoogleIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor">
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
  </svg>
);

const ShieldIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    <path d="M9 12l2 2 4-4"/>
  </svg>
);

const HeartIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
  </svg>
);

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
);

const AlertIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="8" x2="12" y2="12"/>
    <line x1="12" y1="16" x2="12.01" y2="16"/>
  </svg>
);

const FolderIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
  </svg>
);

const MusicNoteIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
  </svg>
);

const RefreshIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 2v6h-6"/>
    <path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
    <path d="M3 22v-6h6"/>
    <path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
  </svg>
);

const CrownIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor">
    <path d="M5 16L3 5l5.5 5L12 4l3.5 6L21 5l-2 11H5z"/>
    <path d="M19 19H5v2h14v-2z"/>
  </svg>
);

const LogoutIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
    <polyline points="16 17 21 12 16 7"/>
    <line x1="21" y1="12" x2="9" y2="12"/>
  </svg>
);

const LinkIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
  </svg>
);

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6"/>
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
    <line x1="10" y1="11" x2="10" y2="17"/>
    <line x1="14" y1="11" x2="14" y2="17"/>
  </svg>
);

// ============================================
// 3D ANIMATED BACKGROUND
// ============================================

const AnimatedBackground = () => (
  <div className="bg-3d-container">
    <div className="bg-orb bg-orb-1" />
    <div className="bg-orb bg-orb-2" />
    <div className="bg-orb bg-orb-3" />
    <div className="bg-orb bg-orb-4" />
    <div className="bg-grid" />
    <div className="bg-noise" />
    <div className="particles-container">
      {[...Array(12)].map((_, i) => (
        <div key={i} className="particle" />
      ))}
    </div>
  </div>
);

// ============================================
// CONFETTI COMPONENT
// ============================================

const Confetti = ({ show }) => {
  if (!show) return null;
  
  return (
    <div className="confetti-container">
      {[...Array(50)].map((_, i) => (
        <div
          key={i}
          className="confetti"
          style={{
            left: `${Math.random() * 100}%`,
            animationDelay: `${Math.random() * 3}s`,
            animationDuration: `${3 + Math.random() * 2}s`,
          }}
        />
      ))}
    </div>
  );
};

// ============================================
// PREMIUM 3D SPINNER
// ============================================

const Spinner3D = () => (
  <div className="spinner-3d">
    <div className="spinner-ring" />
    <div className="spinner-ring" />
    <div className="spinner-ring" />
    <div className="spinner-center">
      <MusicNoteIcon />
    </div>
  </div>
);

// ============================================
// LANDING PAGE - UNAUTHENTICATED
// ============================================

const LandingPage = ({ onGoogleSignIn, isLoading }) => {
  const buttonRef = useRef(null);
  
  const handleClick = (e) => {
    const button = buttonRef.current;
    const ripple = document.createElement('span');
    ripple.classList.add('btn-ripple');
    const rect = button.getBoundingClientRect();
    ripple.style.left = `${e.clientX - rect.left}px`;
    ripple.style.top = `${e.clientY - rect.top}px`;
    button.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
    
    onGoogleSignIn();
  };
  
  return (
    <motion.div 
      className="landing"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.6 }}
    >
      <div className="landing-content">
        <motion.div 
          className="logo"
          initial={{ scale: 0, rotate: -180 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ type: "spring", duration: 1, bounce: 0.4 }}
        >
          <div className="logo-container">
            <div className="logo-glow" />
            <svg viewBox="0 0 24 24" fill="#1db954">
              <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
            </svg>
          </div>
        </motion.div>

        <motion.div 
          className="hero"
          initial={{ y: 40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.2 }}
        >
          <h1 className="hero-title">
            <span className="hero-title-line white-text">Organize Your</span>
            <span className="hero-title-line gradient-text">Music Library</span>
          </h1>
          <p className="hero-subtitle">
            AI-powered playlist curation that transforms your <strong>Liked Songs</strong> into 
            perfectly organized genre-based collections. <em>Automatic daily updates.</em>
          </p>
        </motion.div>

        {/* Features Card */}
        <motion.div 
          className="pricing-card"
          initial={{ y: 40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.3 }}
        >
          <div className="pricing-header">
            <HeartIcon />
            <span>Made out of Love for Tana</span>
          </div>
          <div className="pricing-price">
            <span className="price-amount">25 </span>
            <span className="price-period">spots only!</span> 
          </div>
          <ul className="pricing-features">
            <li><CheckIcon /> Automatic daily organization</li>
            <li><CheckIcon /> AI-powered genre classification</li>
            <li><CheckIcon /> Multi-language support</li>
            <li><CheckIcon /> Limited to 24 users</li>
          </ul>
        </motion.div>

        {/* Google Sign In Button */}
        <motion.button
          ref={buttonRef}
          className="btn btn-google"
          onClick={handleClick}
          disabled={isLoading}
          initial={{ y: 40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.4 }}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
        >
          <span className="btn-icon">
            <GoogleIcon />
          </span>
          {isLoading ? 'Signing in...' : 'Continue with Google'}
        </motion.button>

        {/* Trust Card */}
        <motion.div 
          className="trust-card"
          initial={{ y: 40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.6 }}
        >
          <div className="trust-card-item">
            <div className="trust-card-icon">
              <ShieldIcon />
            </div>
            <div className="trust-card-text">
              <h4>Privacy First</h4>
              <p>Your music stays on Spotify. We never store your library data.</p>
            </div>
          </div>
          
          <div className="trust-card-item">
            <div className="trust-card-icon">
              <HeartIcon />
            </div>
            <div className="trust-card-text">
              <h4>Made with Love</h4>
              <p>A passion project made for my dear girlfriend Tana</p>
            </div>
          </div>
        </motion.div>
      </div>
    </motion.div>
  );
};

// ============================================
// DASHBOARD - AUTHENTICATED USER
// ============================================

const Dashboard = ({ 
  user, 
  subscription,
  userLimit,
  showLimitMessage,
  onActivate,
  onLinkSpotify, 
  onTriggerScan,
  onLogout,
  onDeleteAccount,
  onLogInterest,
  isLoading,
  showDeleteModal,
  setShowDeleteModal,
  scanCooldown
}) => {
  const isActive = subscription?.status === 'active';
  const spotifyLinked = subscription?.spotify_linked;
  const limitReached = userLimit?.limit_reached;
  
  return (
    <motion.div 
      className="dashboard"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.6 }}
    >
      <div className="dashboard-content">
        {/* Header */}
        <div className="dashboard-header">
          <div className="user-info">
            <img 
              src={user?.photoURL || 'https://via.placeholder.com/40'} 
              alt="Profile" 
              className="user-avatar"
            />
            <div className="user-details">
              <h3>{user?.displayName || 'User'}</h3>
              <p>{user?.email}</p>
            </div>
          </div>
          <div className="header-actions">
            <button className="btn btn-icon-only btn-danger-ghost" onClick={() => setShowDeleteModal(true)} title="Delete Account">
              <TrashIcon />
            </button>
            <button className="btn btn-icon-only" onClick={onLogout} title="Sign Out">
              <LogoutIcon />
            </button>
          </div>
        </div>

        {/* Limit Reached Message */}
        <AnimatePresence>
          {showLimitMessage && (
            <motion.div 
              className="limit-toast"
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3 }}
            >
              <AlertIcon />
              <span>Maximum user limit reached. We'll notify you when more spots open up!</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Delete Account Modal */}
        <AnimatePresence>
          {showDeleteModal && (
            <motion.div 
              className="modal-overlay"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <motion.div 
                className="modal-content"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
              >
                <div className="modal-icon danger">
                  <TrashIcon />
                </div>
                <h3>Delete Account?</h3>
                <p>This will permanently delete your account and all associated data. This action cannot be undone.</p>
                <div className="modal-actions">
                  <button 
                    className="btn btn-ghost" 
                    onClick={() => setShowDeleteModal(false)}
                    disabled={isLoading}
                  >
                    Cancel
                  </button>
                  <button 
                    className="btn btn-danger" 
                    onClick={onDeleteAccount}
                    disabled={isLoading}
                  >
                    {isLoading ? 'Deleting...' : 'Delete Account'}
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Account Status Card */}
        <motion.div 
          className={`subscription-card ${isActive ? 'active' : 'inactive'}`}
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.1 }}
        >
          <div className="subscription-header">
            <CrownIcon />
            <span>{isActive ? 'Account Active' : 'Activate Your Account'}</span>
          </div>
          
          {isActive ? (
            <div className="subscription-details">
              <p>Account active until: <strong>{new Date(subscription.end_date).toLocaleDateString()}</strong></p>
              {subscription.last_scan_at && (
                <p>Last scan: {new Date(subscription.last_scan_at).toLocaleString()}</p>
              )}
              <p>Total songs organized: <strong>{subscription.total_songs_organized || 0}</strong></p>
            </div>
          ) : (
            <div className="subscription-cta">
              {limitReached ? (
                <>
                  <p className="limit-warning">Maximum user limit (24) reached.</p>
                  <button 
                    className="btn btn-primary btn-disabled"
                    onClick={onLogInterest}
                    disabled={isLoading}
                  >
                    {isLoading ? 'Processing...' : 'Notify me when spots open'}
                  </button>
                </>
              ) : (
                <>
                  <p>Click below to activate your free account and start organizing your music!</p>
                  <button 
                    className="btn btn-primary"
                    onClick={onActivate}
                    disabled={isLoading}
                  >
                    {isLoading ? 'Activating...' : 'Activate Free Account'}
                  </button>
                </>
              )}
            </div>
          )}
        </motion.div>

        {/* Spotify Connection */}
        {isActive && (
          <motion.div 
            className={`spotify-card ${spotifyLinked ? 'linked' : 'unlinked'}`}
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.2 }}
          >
            <div className="spotify-header">
              <SpotifyIcon />
              <span>{spotifyLinked ? 'Spotify Connected' : 'Connect Spotify'}</span>
            </div>
            
            {spotifyLinked ? (
              <div className="spotify-actions">
                <p>Your Spotify account is connected. Songs are organized automatically every 24 hours.</p>
                <button 
                  className="btn btn-secondary"
                  onClick={onTriggerScan}
                  disabled={isLoading || scanCooldown > 0}
                >
                  <RefreshIcon />
                  {isLoading ? 'Scanning...' : scanCooldown > 0 ? `Wait ${scanCooldown}s` : 'Scan Now'}
                </button>
              </div>
            ) : (
              <div className="spotify-cta">
                <p>Link your Spotify account to start organizing your liked songs.</p>
                <button 
                  className="btn btn-spotify"
                  onClick={onLinkSpotify}
                  disabled={isLoading}
                >
                  <LinkIcon />
                  {isLoading ? 'Connecting...' : 'Connect Spotify'}
                </button>
              </div>
            )}
          </motion.div>
        )}

        {/* How it Works */}
        <motion.div 
          className="info-card"
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.3 }}
        >
          <h3>How it Works</h3>
          <div className="steps">
            <div className={`step ${isActive ? 'completed' : 'active'}`}>
              <div className="step-number">{isActive ? <CheckIcon /> : '1'}</div>
              <div className="step-text">
                <h4>Activate</h4>
                <p>Free account activation</p>
              </div>
            </div>
            <div className={`step ${spotifyLinked ? 'completed' : isActive ? 'active' : ''}`}>
              <div className="step-number">{spotifyLinked ? <CheckIcon /> : '2'}</div>
              <div className="step-text">
                <h4>Connect Spotify</h4>
                <p>Link your Spotify account</p>
              </div>
            </div>
            <div className={`step ${spotifyLinked ? 'active' : ''}`}>
              <div className="step-number">3</div>
              <div className="step-text">
                <h4>Enjoy</h4>
                <p>Playlists organized daily</p>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </motion.div>
  );
};

// ============================================
// STATUS PAGE - PROCESSING
// ============================================

const StatusPage = ({ status }) => {
  const progressPercent = Math.round(status.progress * 100);
  
  return (
    <motion.div 
      className="status-page"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
    >
      <div className="status-container">
        <motion.div 
          className="spinner-container"
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.5 }}
        >
          <Spinner3D />
        </motion.div>

        <motion.div 
          className="status-text"
          key={status.message}
          initial={{ y: 15, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.4 }}
        >
          <h2 className="status-title">{getStatusTitle(status.status)}</h2>
          <p className="status-message">{status.message}</p>
        </motion.div>

        <div className="progress-container">
          <div className="progress-bar">
            <motion.div 
              className="progress-fill"
              initial={{ width: 0 }}
              animate={{ width: `${progressPercent}%` }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            >
              <div className="progress-glow" />
            </motion.div>
          </div>
          <p className="progress-text">{progressPercent}% complete</p>
        </div>

        <motion.div 
          className="stats"
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          <div className="stat">
            <div className="stat-value">{status.total_songs}</div>
            <div className="stat-label">New Songs</div>
          </div>
          <div className="stat">
            <div className="stat-value">{status.processed_songs}</div>
            <div className="stat-label">Organized</div>
          </div>
          <div className="stat">
            <div className="stat-value">{status.playlists_created}</div>
            <div className="stat-label">Playlists</div>
          </div>
        </motion.div>
      </div>
    </motion.div>
  );
};

// ============================================
// SUCCESS PAGE
// ============================================

const SuccessPage = ({ status, onContinue }) => {
  const [showConfetti, setShowConfetti] = useState(true);
  
  useEffect(() => {
    const timer = setTimeout(() => setShowConfetti(false), 5000);
    return () => clearTimeout(timer);
  }, []);
  
  return (
    <>
      <Confetti show={showConfetti} />
      <motion.div 
        className="success-page"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.5 }}
      >
        <div className="success-container">
          <motion.div 
            className="success-icon"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: "spring", duration: 0.8, bounce: 0.5 }}
          >
            <div className="success-icon-rings">
              <div className="success-ring" />
              <div className="success-ring" />
              <div className="success-ring" />
            </div>
            <div className="success-icon-circle">
              <CheckIcon />
            </div>
          </motion.div>

          <motion.h1 
            className="success-title"
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            Housekeeping Done!
          </motion.h1>

          <motion.p 
            className="success-message"
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.3 }}
          >
            Your liked songs have been organized into curated playlists
          </motion.p>

          <motion.div 
            className="success-stats"
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.4 }}
          >
            <div className="success-stat">
              <div className="success-stat-value">{status.processed_songs}</div>
              <div className="success-stat-label">Songs Organized</div>
            </div>
            <div className="success-stat">
              <div className="success-stat-value">{status.playlists_created}</div>
              <div className="success-stat-label">Playlists Updated</div>
            </div>
          </motion.div>

          <motion.div 
            className="hvb-notice"
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.5 }}
          >
            <div className="hvb-notice-icon">
              <FolderIcon />
            </div>
            <div className="hvb-notice-content">
              <h4>Find Your Playlists</h4>
              <p>Look for playlists named by <strong>genre</strong> or <strong>language</strong> in your Spotify library</p>
            </div>
          </motion.div>

          <motion.button
            className="btn btn-primary"
            onClick={onContinue}
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.6 }}
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
          >
            Back to Dashboard
          </motion.button>
        </div>
      </motion.div>
    </>
  );
};

// ============================================
// ERROR PAGE
// ============================================

const ErrorPage = ({ error, onRetry }) => {
  return (
    <motion.div 
      className="status-page"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
    >
      <div className="error-container">
        <motion.div 
          className="error-icon"
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", duration: 0.6 }}
        >
          <AlertIcon />
        </motion.div>
        <motion.h2 
          className="error-title"
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.1 }}
        >
          Something went wrong
        </motion.h2>
        <motion.p 
          className="error-message"
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.2 }}
        >
          {error || 'An unexpected error occurred. Please try again.'}
        </motion.p>
        <motion.button 
          className="btn btn-primary" 
          onClick={onRetry}
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.3 }}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
        >
          Try Again
        </motion.button>
      </div>
    </motion.div>
  );
};

// ============================================
// HELPER FUNCTIONS
// ============================================

function getStatusTitle(status) {
  const titles = {
    'idle': 'Ready',
    'fetching_songs': 'Fetching Your Music',
    'detecting_languages': 'Detecting Languages',
    'building_artist_map': 'Analyzing Artists',
    'classifying_artists': 'Classifying by Genre',
    'creating_playlists': 'Creating Playlists',
    'populating_playlists': 'Adding Songs',
    'cleaning_up': 'Final Touches',
    'completed': 'All Done!',
    'error': 'Error'
  };
  return titles[status] || 'Processing';
}

const ArrowLeftIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="19" y1="12" x2="5" y2="12"></line>
    <polyline points="12 19 5 12 12 5"></polyline>
  </svg>
);

// ============================================
// ABOUT PAGE
// ============================================

const AboutPage = ({ onBack }) => (
  <motion.div 
    className="about-page"
    initial={{ opacity: 0, scale: 0.95 }}
    animate={{ opacity: 1, scale: 1 }}
    exit={{ opacity: 0, scale: 1.05 }}
    transition={{ duration: 0.3 }}
  >
    <div className="about-content">
      <button className="btn-back" onClick={onBack}>
        <ArrowLeftIcon /> Back
      </button>
      
      <h1>About Spotify Organizer</h1>
      
      <div className="about-section">
        <h2>What is this?</h2>
        <p>Spotify Organizer is an AI-powered tool that automatically categorizes your liked songs into genre-based playlists. We use advanced AI (Gemini) to analyze artist genres and group your music intelligently.</p>
      </div>

      <div className="about-section">
        <h2>How it works</h2>
        <ul>
          <li><strong>Connect:</strong> Link your Spotify account securely.</li>
          <li><strong>Scan:</strong> We scan your liked songs (not the audio files, just metadata).</li>
          <li><strong>Classify:</strong> AI determines the genre for each artist.</li>
          <li><strong>Organize:</strong> Songs are added to playlists like "Pop", "Hip Hop", "Soul", etc.</li>
        </ul>
      </div>

      <div className="about-section">
        <h2>Privacy</h2>
        <p>We only access your playlist and liked songs data. We do not store your personal data or share it with third parties. Authentication is handled securely via Google and Spotify.</p>
      </div>
      
      <div className="about-footer">
        <p>Made with Love for Tana</p>
      </div>
    </div>
  </motion.div>
);

// ============================================
// FOOTER COMPONENT
// ============================================

const Footer = ({ onAboutClick }) => (
  <motion.footer 
    className="app-footer"
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    transition={{ delay: 0.5 }}
  >
    <div className="footer-content">
      <p>Made with Love for Tana</p>
      <button className="footer-link" onClick={onAboutClick}>About</button>
    </div>
  </motion.footer>
);

// ============================================
// MAIN APP COMPONENT
// ============================================

function App() {
  const [currentPage, setCurrentPage] = useState('loading');
  const [user, setUser] = useState(null);
  const [subscription, setSubscription] = useState(null);
  const [userLimit, setUserLimit] = useState({ max_users: 24, current_users: 0, limit_reached: false });
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [status, setStatus] = useState({
    status: 'idle',
    progress: 0,
    message: '',
    total_songs: 0,
    processed_songs: 0,
    playlists_created: 0,
    error: null
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showLimitMessage, setShowLimitMessage] = useState(false);
  const [scanCooldown, setScanCooldown] = useState(0);

  // Cooldown timer
  useEffect(() => {
    if (scanCooldown > 0) {
      const timer = setInterval(() => {
        setScanCooldown(prev => Math.max(0, prev - 1));
      }, 1000);
      return () => clearInterval(timer);
    }
  }, [scanCooldown]);

  // API helper function
  const apiCall = useCallback(async (endpoint, options = {}) => {
    const token = await getIdToken();
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        ...options.headers
      }
    });
    
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const error = new Error(data.detail || `Request failed: ${response.status}`);
      error.status = response.status;
      error.retryAfter = data.retry_after;
      throw error;
    }
    
    return response.json();
  }, []);

  // Fetch subscription status
  const fetchSubscription = useCallback(async () => {
    try {
      const data = await apiCall('/subscription/status');
      setSubscription(data);
      return data;
    } catch (err) {
      console.error('Failed to fetch subscription:', err);
      return null;
    }
  }, [apiCall]);

  // Fetch user limit status (no auth required)
  const fetchUserLimit = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/subscription/limit`);
      const data = await response.json();
      setUserLimit(data);
      return data;
    } catch (err) {
      console.error('Failed to fetch user limit:', err);
      return null;
    }
  }, []);

  // Log interest when user clicks disabled button
  const logInterest = useCallback(async () => {
    try {
      await apiCall('/subscription/interest', { method: 'POST' });
      setShowLimitMessage(true);
      setTimeout(() => setShowLimitMessage(false), 5000);
    } catch (err) {
      console.error('Failed to log interest:', err);
    }
  }, [apiCall]);

  // Auth state listener
  useEffect(() => {
    const unsubscribe = onAuthChange(async (firebaseUser) => {
      if (firebaseUser) {
        setUser(firebaseUser);
        await Promise.all([fetchSubscription(), fetchUserLimit()]);
        setCurrentPage('dashboard');
      } else {
        setUser(null);
        setSubscription(null);
        setCurrentPage('landing');
      }
    });

    // Fetch limit on initial load (even before auth)
    fetchUserLimit();

    return () => unsubscribe();
  }, [fetchSubscription, fetchUserLimit]);

  // Handle URL params (Spotify callback)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const spotifyLinked = params.get('spotify_linked');
    const spotifyError = params.get('spotify_error');

    if (spotifyLinked === 'true') {
      window.history.replaceState({}, '', '/');
      fetchSubscription();
    } else if (spotifyError) {
      setError(`Spotify connection failed: ${spotifyError}`);
      setCurrentPage('error');
      window.history.replaceState({}, '', '/');
    }
  }, [fetchSubscription]);

  // Poll for processing status
  useEffect(() => {
    let interval;
    let pollCount = 0;
    
    if (currentPage === 'processing') {
      interval = setInterval(async () => {
        try {
          const data = await apiCall('/process/status');
          setStatus(data);
          pollCount++;

          if (data.status === 'completed') {
            setCurrentPage('success');
          } else if (data.status === 'error') {
            setError(data.error);
            setCurrentPage('error');
          } else if (data.status === 'idle' && pollCount > 3) {
            // If we get 'idle' after polling a few times, it means the scan 
            // completed and state was cleared. Redirect to dashboard.
            await fetchSubscription();
            setCurrentPage('dashboard');
          }
        } catch (err) {
          console.error('Status poll error:', err);
        }
      }, 1000);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [currentPage, apiCall, fetchSubscription]);

  // Handle Google Sign In
  const handleGoogleSignIn = async () => {
    setIsLoading(true);
    try {
      const { idToken } = await signInWithGoogle();
      await apiCall('/auth/google', {
        method: 'POST',
        body: JSON.stringify({ id_token: idToken })
      });
      // Auth state listener will handle the rest
    } catch (err) {
      console.error('Sign in error:', err);
      setError('Failed to sign in. Please try again.');
      setCurrentPage('error');
    } finally {
      setIsLoading(false);
    }
  };

  // Handle Account Activation
  const handleActivate = async () => {
    setIsLoading(true);
    try {
      await apiCall('/auth/activate', { method: 'POST' });
      await fetchSubscription();
    } catch (err) {
      console.error('Activation error:', err);
      if (err.message.includes('limit')) {
        setShowLimitMessage(true);
        setTimeout(() => setShowLimitMessage(false), 5000);
      } else {
        setError('Failed to activate account. Please try again.');
        setCurrentPage('error');
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Handle Account Deletion
  const handleDeleteAccount = async () => {
    setIsLoading(true);
    try {
      await apiCall('/user/account', { method: 'DELETE' });
      setShowDeleteModal(false);
      await signOut();
      setCurrentPage('landing');
    } catch (err) {
      console.error('Delete account error:', err);
      setError('Failed to delete account. Please try again.');
      setShowDeleteModal(false);
      setCurrentPage('error');
    } finally {
      setIsLoading(false);
    }
  };

  // Handle Spotify Linking
  const handleLinkSpotify = async () => {
    setIsLoading(true);
    try {
      const data = await apiCall('/auth/spotify/login');
      window.location.href = data.auth_url;
    } catch (err) {
      console.error('Spotify link error:', err);
      setError('Failed to connect to Spotify. Please try again.');
      setCurrentPage('error');
    } finally {
      setIsLoading(false);
    }
  };

  // Handle Scan Trigger
  const handleTriggerScan = async () => {
    setIsLoading(true);
    try {
      await apiCall('/process/trigger', { method: 'POST' });
      setStatus({
        status: 'fetching_songs',
        progress: 0,
        message: 'Starting scan...',
        total_songs: 0,
        processed_songs: 0,
        playlists_created: 0,
        error: null
      });
      setCurrentPage('processing');
    } catch (err) {
      console.error('Scan trigger error:', err);
      
      if (err.status === 429) {
        setScanCooldown(Math.ceil(err.retryAfter || 60));
        // Stay on dashboard, let the button show the timer
        return;
      }
      
      setError(err.message || 'Failed to start scan');
      setCurrentPage('error');
    } finally {
      setIsLoading(false);
    }
  };

  // Handle Logout
  const handleLogout = async () => {
    await signOut();
    setCurrentPage('landing');
  };

  // Handle retry/reset
  const handleRetry = () => {
    setError(null);
    if (user) {
      setCurrentPage('dashboard');
    } else {
      setCurrentPage('landing');
    }
  };

  return (
    <div className="app">
      <AnimatedBackground />
      
      <AnimatePresence mode="wait">
        {currentPage === 'loading' && (
          <motion.div 
            key="loading"
            className="loading-page"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <Spinner3D />
          </motion.div>
        )}

        {currentPage === 'landing' && (
          <LandingPage 
            key="landing"
            onGoogleSignIn={handleGoogleSignIn} 
            isLoading={isLoading} 
          />
        )}
        
        {currentPage === 'dashboard' && (
          <Dashboard
            key="dashboard"
            user={user}
            subscription={subscription}
            userLimit={userLimit}
            showLimitMessage={showLimitMessage}
            onActivate={handleActivate}
            onLinkSpotify={handleLinkSpotify}
            onTriggerScan={handleTriggerScan}
            onLogout={handleLogout}
            onDeleteAccount={handleDeleteAccount}
            onLogInterest={logInterest}
            isLoading={isLoading}
            showDeleteModal={showDeleteModal}
            setShowDeleteModal={setShowDeleteModal}
            scanCooldown={scanCooldown}
          />
        )}
        
        {currentPage === 'processing' && (
          <StatusPage 
            key="processing"
            status={status} 
          />
        )}
        
        {currentPage === 'success' && (
          <SuccessPage 
            key="success"
            status={status} 
            onContinue={() => {
              fetchSubscription();
              setCurrentPage('dashboard');
            }} 
          />
        )}
        
        {currentPage === 'error' && (
          <ErrorPage 
            key="error"
            error={error} 
            onRetry={handleRetry} 
          />
        )}

        {currentPage === 'about' && (
          <AboutPage 
            key="about"
            onBack={() => user ? setCurrentPage('dashboard') : setCurrentPage('landing')} 
          />
        )}
      </AnimatePresence>

      {currentPage !== 'about' && currentPage !== 'loading' && (
        <Footer onAboutClick={() => setCurrentPage('about')} />
      )}
    </div>
  );
}

export default App;
