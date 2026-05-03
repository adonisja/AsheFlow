import { useState, useCallback } from 'react';

interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'warning' | 'default';
}

interface ConfirmState extends ConfirmOptions {
  open: boolean;
  onConfirm: () => void;
}

const CLOSED: ConfirmState = {
  open: false,
  title: '',
  message: '',
  onConfirm: () => {},
};

export function useConfirm() {
  const [state, setState] = useState<ConfirmState>(CLOSED);

  const confirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
    return new Promise(resolve => {
      setState({
        ...opts,
        open: true,
        onConfirm: () => {
          setState(CLOSED);
          resolve(true);
        },
      });
    });
  }, []);

  const cancel = useCallback(() => {
    setState(CLOSED);
  }, []);

  return { confirmState: state, confirm, cancelConfirm: cancel };
}
