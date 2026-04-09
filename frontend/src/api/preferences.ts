import axiosClient from './axiosClient';

// TYPES
export interface EmployeeOffDay {
  id: string;
  employee_id: string;
  day_of_week: string;
  status: 'pending' | 'approved' | 'rejected';
}

export interface EmployeeRelationship {
  id: string;
  employee_id: string;
  target_employee_id: string;
  relationship_type: 'fav' | 'ban';
}

// API CALLS
export const getOffDays = async (employeeId: string) => {
  const { data } = await axiosClient.get<EmployeeOffDay[]>(`/employee-off-days/${employeeId}`);
  return data;
};

export const createOffDay = async (employeeId: string, dayOfWeek: string) => {
  const { data } = await axiosClient.post<EmployeeOffDay>('/employee-off-days/', {
    employee_id: employeeId,
    day_of_week: dayOfWeek,
  });
  return data;
};

export const deleteOffDay = async (offDayId: string) => {
  await axiosClient.delete(`/employee-off-days/${offDayId}`);
};

export const approveOffDay = async (offDayId: string) => {
  const { data } = await axiosClient.patch(`/employee-off-days/${offDayId}/approve`);
  return data;
};

export const rejectOffDay = async (offDayId: string) => {
  const { data } = await axiosClient.patch(`/employee-off-days/${offDayId}/reject`);
  return data;
};

export const getRelationships = async (employeeId: string) => {
  const { data } = await axiosClient.get<EmployeeRelationship[]>(`/employee-relationships/${employeeId}`);
  return data;
};

export const createRelationship = async (employeeId: string, targetEmployeeId: string, type: 'fav' | 'ban') => {
  const { data } = await axiosClient.post<EmployeeRelationship>('/employee-relationships/', {
    employee_id: employeeId,
    target_employee_id: targetEmployeeId,
    relationship_type: type,
  });
  return data;
};

export const deleteRelationship = async (relationshipId: string) => {
  await axiosClient.delete(`/employee-relationships/${relationshipId}`);
};

export const getSchedule = async (employeeId: string, startDate: string, endDate: string) => {
  const { data } = await axiosClient.get(`/schedule/${employeeId}`, {
    params: { start_date: startDate, end_date: endDate }
  });
  return data;
};
