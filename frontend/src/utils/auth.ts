import { fetchAuthSession, getCurrentUser } from 'aws-amplify/auth';

export const getUserGroups = async (): Promise<string[]> => {
  try {
    const session = await fetchAuthSession();
    // Amplify automatically decodes the JWT payload for us
    const payload = session.tokens?.idToken?.payload;
    
    // Extract the groups, defaulting to an empty array if none exist
    const groups = payload?.['cognito:groups'];
    
    // Ensure it's an array of strings
    if (Array.isArray(groups)) {
        return groups as string[];
    }
    return [];
  } catch (error) {
    console.error('Error fetching user groups:', error);
    return [];
  }
};
