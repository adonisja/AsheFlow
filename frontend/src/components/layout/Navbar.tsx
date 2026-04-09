import React, { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import { useAuth } from '../../contexts/AuthContext';
import axiosClient from '../../api/axiosClient';
import { 
  LogOut, 
  Menu, 
  X, 
  Home, 
  Calendar, 
  Settings, 
  Truck, 
  ClipboardCheck, 
  Users 
} from 'lucide-react';

const Navbar = () => {
  const { user, groups } = useAuth();
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  // Helper check for management/dispatch roles
  const isDispatchOrAbove = groups.some(role => ['admin', 'management', 'dispatch'].includes(role));
  const isAdminOrMgmt = groups.some(role => ['admin', 'management'].includes(role));

  const handleTestAPI = async () => {
    try {
      const response = await axiosClient.get('/employees/');
      console.log('API Success Response:', response.data);
      alert('Success!');
      setTestResult(JSON.stringify(response.data, null, 2));
    } catch (error) {
      console.error('API Error Response:', error);
      alert('Failed!');
      setTestResult(String(error));
    }
  };

  const handleSignOut = async () => {
    try {
      await signOut();
      navigate('/login');
    } catch (error) {
      console.error('Error signing out: ', error);
    }
  };

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center px-3 py-2 rounded-md text-sm font-medium ${
      isActive 
        ? 'bg-indigo-700 text-white' 
        : 'text-indigo-100 hover:bg-indigo-500 hover:text-white'
    }`;

  const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center block px-3 py-2 rounded-md text-base font-medium ${
      isActive 
        ? 'bg-indigo-700 text-white' 
        : 'text-indigo-100 hover:bg-indigo-500 hover:text-white'
    }`;

  return (
    <nav className="bg-indigo-600">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center">
            <div className="flex-shrink-0 text-white font-bold text-xl flex items-center gap-2">
              <Truck className="h-6 w-6" />
              AsheFlow
            </div>
            
            {/* Desktop Navigation */}
            <div className="hidden md:block">
              <div className="ml-10 flex items-baseline space-x-6">
                <NavLink to="/" className={navLinkClass}>
                  <Home className="w-4 h-4 mr-2" /> Home
                </NavLink>
                
                {/* Worker Links (Everyone sees these) */}
                <NavLink to="/schedule" className={navLinkClass}>
                  <Calendar className="w-4 h-4 mr-2" /> My Schedule
                </NavLink>
                <NavLink to="/preferences" className={navLinkClass}>
                  <Settings className="w-4 h-4 mr-2" /> Preferences
                </NavLink>

                {/* Management Links */}
                {isDispatchOrAbove && (
                  <NavLink to="/dispatch" className={navLinkClass}>
                    <ClipboardCheck className="w-4 h-4 mr-2" /> Dispatch Center
                  </NavLink>
                )}
                {isAdminOrMgmt && (
                  <NavLink to="/assets" className={navLinkClass}>
                    <Users className="w-4 h-4 mr-2" /> Assets & Users
                  </NavLink>
                )}
              </div>
            </div>
          </div>

            {/* User Info & Logout (Desktop) */}
          <div className="hidden md:block">
            <div className="ml-4 flex items-center md:ml-6 gap-6">
              <button 
                onClick={handleTestAPI}
                className="bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded"
              >
                Test API
              </button>
              <span className="text-indigo-100 text-sm">
                {user?.displayName || user?.username}
              </span>
              <button
                onClick={handleSignOut}
                className="flex items-center gap-2 px-3 py-2 rounded-md text-indigo-200 hover:text-white hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-indigo-600 focus:ring-white font-medium"
                title="Sign out"
              >
                <span>Signout</span>
                <LogOut className="h-5 w-5" />
              </button>
            </div>
          </div>

          {/* Mobile menu button */}
          <div className="-mr-2 flex md:hidden">
            <button
              onClick={() => setIsOpen(!isOpen)}
              className="inline-flex items-center justify-center p-2 rounded-md text-indigo-200 hover:text-white hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-indigo-600 focus:ring-white"
            >
              <span className="sr-only">Open main menu</span>
              {isOpen ? <X className="block h-6 w-6" /> : <Menu className="block h-6 w-6" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {isOpen && (
        <div className="md:hidden">
          <div className="px-2 pt-2 pb-3 space-y-1 sm:px-3">
            <NavLink to="/" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
              <Home className="w-5 h-5 mr-3" /> Home
            </NavLink>
            <NavLink to="/schedule" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
              <Calendar className="w-5 h-5 mr-3" /> My Schedule
            </NavLink>
            <NavLink to="/preferences" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
              <Settings className="w-5 h-5 mr-3" /> Preferences
            </NavLink>
            
            {isDispatchOrAbove && (
              <NavLink to="/dispatch" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <ClipboardCheck className="w-5 h-5 mr-3" /> Dispatch Center
              </NavLink>
            )}
            {isAdminOrMgmt && (
              <NavLink to="/assets" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <Users className="w-5 h-5 mr-3" /> Assets & Users
              </NavLink>
            )}
          </div>
          <div className="pt-4 pb-3 border-t border-indigo-700">
            <div className="flex items-center px-5">
              <div className="text-base font-medium text-white">{user?.displayName || user?.username}</div>
            </div>
            <div className="mt-3 px-2 space-y-1">
              <button
                onClick={handleSignOut}
                className="flex items-center w-full px-3 py-2 rounded-md text-base font-medium text-indigo-100 hover:text-white hover:bg-indigo-500"
              >
                <LogOut className="w-5 h-5 mr-3" /> Sign out
              </button>
            </div>
          </div>
        </div>
      )}
      {testResult && (
        <div className="bg-gray-800 text-green-400 p-4 font-mono text-sm max-h-40 overflow-auto">
          <pre>{testResult}</pre>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
