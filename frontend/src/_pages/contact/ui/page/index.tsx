import styles from "./styles.module.scss";
import classNames from "classnames";
import {
  Button,
  Input,
  RequiredStar,
  Textarea,
} from "shared/ui";

export const Contact = () => {
  return (
    <>
      <main className={classNames("wrapper", styles.container)}>
        <div className={styles.content}>
          <div className={styles.left}>
            <p className={styles.title}>Нужна дополнительная информация?</p>
            <p className={styles.description}>
              Остались вопросы или нужно больше информации? Свяжитесь с нами по контактам ниже, и наша команда с радостью проконсультирует вас.
            </p>
            <div className={styles.info}>
              <div className={styles.infoItem}>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="28"
                  height="28"
                  fill="none"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  viewBox="0 0 24 24"
                >
                  <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z"></path>
                </svg>
                <p className={styles.phone}>+7 (747) 205-1507</p>
              </div>
              <div className={styles.infoItem}>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="28"
                  height="28"
                  fill="currentColor"
                  stroke="currentColor"
                  strokeWidth="0"
                  viewBox="0 0 512 512"
                >
                  <rect
                    width="416"
                    height="320"
                    x="48"
                    y="96"
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="32"
                    rx="40"
                    ry="40"
                  ></rect>
                  <path
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="32"
                    d="M112 160l144 112 144-112"
                  ></path>
                </svg>
                <p className={styles.phone}>zholdas.alnur@gmail.com</p>
              </div>
              <div className={styles.infoItem}>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="28"
                  height="28"
                  fill="currentColor"
                  stroke="currentColor"
                  strokeWidth="0"
                  viewBox="0 0 512 512"
                  className={styles.location}
                >
                  <path d="M256 32C167.67 32 96 96.51 96 176c0 128 160 304 160 304s160-176 160-304c0-79.49-71.67-144-160-144zm0 224a64 64 0 1164-64 64.07 64.07 0 01-64 64z"></path>
                </svg>
                <p className={styles.phone}>Almaty, Kazakhstan</p>
              </div>
            </div>
          </div>
        </div>
      </main>
    </>
  );
};
