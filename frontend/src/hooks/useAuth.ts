import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { authApi } from '../api/auth';
import { setUser, logout } from '../store/authSlice';
import type { RootState } from '../store';

export function useAuth() {
  const dispatch = useDispatch();
  const { user, accessToken } = useSelector((state: RootState) => state.auth);

  useEffect(() => {
    if (accessToken && !user) {
      authApi
        .me()
        .then((me) => dispatch(setUser(me)))
        .catch(() => dispatch(logout()));
    }
  }, [accessToken, user, dispatch]);

  return { user, accessToken };
}
