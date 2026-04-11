import axiosClient from './axiosClient';
import type { EmployeeRelationship } from './preferences';

export const getAllEmployeeRelationships = async (): Promise<Record<string, { favs: string[], bans: string[] }>> => {
  const { data } = await axiosClient.get<EmployeeRelationship[]>('/employee-relationships/');
  
  const map: Record<string, { favs: string[], bans: string[] }> = {};
  
  data.forEach((rel) => {
    if (!map[rel.employee_id]) {
      map[rel.employee_id] = { favs: [], bans: [] };
    }
    
    if (rel.relationship_type === 'fav') {
      map[rel.employee_id].favs.push(rel.target_employee_id);
    } else if (rel.relationship_type === 'ban') {
      map[rel.employee_id].bans.push(rel.target_employee_id);
    }
  });

  return map;
};
