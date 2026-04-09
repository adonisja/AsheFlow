import axiosClient from './axiosClient';

export interface TimeOffRequest {
  id: string;
  employee_id: string;
  date: string;
  status: 'pending' | 'approved' | 'rejected';
}

export const getTimeOffRequests = async (employeeId: string) => {
  const { data } = await axiosClient.get<TimeOffRequest[]>(`/time-off-requests/${employeeId}`);
  return data;
};

export const createTimeOffRequest = async (employeeId: string, date: string) => {
  const { data } = await axiosClient.post<TimeOffRequest>('/time-off-requests/', {
    employee_id: employeeId,
    date,
  });
  return data;
};

export const deleteTimeOffRequest = async (requestId: string) => {
  await axiosClient.delete(`/time-off-requests/${requestId}`);
};

export const approveTimeOffRequest = async (requestId: string) => {
  const { data } = await axiosClient.patch(`/time-off-requests/${requestId}/approve`);
  return data;
};

export const rejectTimeOffRequest = async (requestId: string) => {
  const { data } = await axiosClient.patch(`/time-off-requests/${requestId}/reject`);
  return data;
};
