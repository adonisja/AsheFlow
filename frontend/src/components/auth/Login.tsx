import React, { useState, useEffect } from 'react';
import { signIn, signUp, signInWithRedirect, confirmSignIn } from 'aws-amplify/auth';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { Truck, Eye, EyeOff } from 'lucide-react';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [isSignUp, setIsSignUp] = useState(false);
  const [isNewPasswordRequired, setIsNewPasswordRequired] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  
  const navigate = useNavigate();
  const { isAuthenticated, checkAuth } = useAuth();

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/');
    }
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccessMsg('');
    
    try {
      if (isNewPasswordRequired) {
        const response = await confirmSignIn({ challengeResponse: newPassword });
        if (response.isSignedIn) {
          await checkAuth();
        } else {
          setError(`Action required: ${response.nextStep?.signInStep}`);
        }
      } else if (isSignUp) {
        await signUp({ 
          username: email, 
          password,
          options: { userAttributes: { email } }
        });
        setSuccessMsg('Sign up successful, please log in');
        setIsSignUp(false);
        setPassword('');
      } else {
        const response = await signIn({ 
          username: email, 
          password,
          options: { authFlowType: 'USER_PASSWORD_AUTH' }
        });
        console.log("SignIn response:", response);

        if (response.nextStep?.signInStep === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED') {
          setIsNewPasswordRequired(true);
          setSuccessMsg('You are logging in with a temporary password. Please set a new permanent password.');
        } else if (response.isSignedIn) {
          await checkAuth();
        } else {
          setError(`Action required: ${response.nextStep?.signInStep}`);
        }
      }
    } catch (err: any) {
      setError(err.message || (isSignUp ? 'Sign up failed' : 'Login failed'));
    }
  };

  const handleDiscordSignIn = () => {
    signInWithRedirect({ provider: { custom: 'Discord' } });
  };

  const handleGoogleSignIn = () => {
    signInWithRedirect({ provider: 'Google' });
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4 relative overflow-hidden"
         style={{ background: 'linear-gradient(135deg, hsl(243 75% 97%), hsl(220 20% 97%), hsl(252 85% 97%))' }}>
      {/* Decorative blobs */}
      <div className="absolute top-[-20%] left-[-10%] w-[500px] h-[500px] rounded-full opacity-20"
           style={{ background: 'radial-gradient(circle, hsl(243 75% 59% / 0.3), transparent 70%)' }} />
      <div className="absolute bottom-[-20%] right-[-10%] w-[400px] h-[400px] rounded-full opacity-15"
           style={{ background: 'radial-gradient(circle, hsl(262 83% 58% / 0.3), transparent 70%)' }} />

      <div className="w-full max-w-sm animate-slide-up relative z-10">
        {/* Logo */}
        <div className="flex items-center justify-center gap-3 mb-10">
          <div className="flex items-center justify-center w-11 h-11 rounded-xl gradient-primary shadow-lg shadow-primary/30">
            <Truck className="h-5 w-5 text-primary-foreground" />
          </div>
          <span className="text-2xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-primary to-violet">AsheFlow</span>
        </div>

        <div className="card-elevated p-8 backdrop-blur-sm bg-card/90">
          <h2 className="text-xl font-semibold text-center text-foreground mb-1">
            {isNewPasswordRequired ? 'Update Password' : (isSignUp ? 'Create your account' : 'Welcome back')}
          </h2>
          <p className="text-subtle text-center mb-8">
            {isNewPasswordRequired ? 'A new password is required to continue' : (isSignUp ? 'Get started with AsheFlow' : 'Sign in to your account')}
          </p>

          {error && (
            <div className="bg-danger/5 text-danger px-4 py-3 rounded-xl mb-6 text-sm font-medium border border-danger/20">
              {error}
            </div>
          )}
          
          {successMsg && (
            <div className="bg-success/5 text-success px-4 py-3 rounded-xl mb-6 text-sm font-medium border border-success/20">
              {successMsg}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isNewPasswordRequired ? (
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">New Password</label>
                <div className="relative">
                  <input
                    type={showNewPassword ? "text" : "password"}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    className="input-field pr-10"
                    placeholder="••••••••"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword(!showNewPassword)}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {showNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1.5">Email</label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="input-field"
                    placeholder="you@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1.5">Password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      className="input-field pr-10"
                      placeholder="••••••••"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </>
            )}

            <button type="submit" className="btn-primary w-full mt-2">
              {isNewPasswordRequired ? 'Set new password' : (isSignUp ? 'Create account' : 'Sign in')}
            </button>
          </form>

          {!isNewPasswordRequired && (
            <>
              <div className="mt-6 text-center">
                <button 
                  type="button" 
                  onClick={() => {
                    setIsSignUp(!isSignUp);
                    setError('');
                    setSuccessMsg('');
                  }} 
                  className="text-sm text-muted-foreground hover:text-primary transition-colors"
                >
                  {isSignUp ? 'Already have an account? Sign in' : "Don't have an account? Sign up"}
                </button>
              </div>

              <div className="mt-8">
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-border" />
                  </div>
                  <div className="relative flex justify-center text-xs">
                    <span className="px-3 bg-card text-muted-foreground uppercase tracking-wider">or</span>
                  </div>
                </div>

                <div className="mt-6 space-y-3">
                  <button
                    onClick={handleDiscordSignIn}
                    type="button"
                    className="btn-secondary w-full"
                  >
                    Continue with Discord
                  </button>
                  <button
                    onClick={handleGoogleSignIn}
                    type="button"
                    className="btn-secondary w-full"
                  >
                    Continue with Google
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
