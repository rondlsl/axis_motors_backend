import {IProps} from "./props";
import styles from "./styles.module.scss";
import {Logo} from "shared/ui";
import Link from "next/link";
import classNames from "classnames";

export const Footer = (props: IProps) => {
    return (
        <footer className={styles.container}>
            <div className={classNames(styles.content, "wrapper")}>
                <div className={styles.top}>
                    <div className={"space-y-3"}>
                        <Logo mode={"secondary"}/>
                        <p className={"text-sm text-typeSecondary"}>
                            Мы стремимся создать сообщество, где каждый может делиться своими ресурсами, открывая новые
                            возможности для заработка и свободы передвижения. <br/>Azv Motors — ваш надежный партнер на пути к
                            миру, где авто доступно каждому.
                        </p>
                    </div>
                    <div className={styles.socials}>
                        <Link href={""} className={styles.social}>
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                width="1em"
                                height="1em"
                                fill="currentColor"
                                stroke="currentColor"
                                strokeWidth="0"
                                viewBox="0 0 512 512"
                            >
                                <path
                                    stroke="none"
                                    d="M512 256C512 114.6 397.4 0 256 0S0 114.6 0 256c0 120 82.7 220.8 194.2 248.5V334.2h-52.8V256h52.8v-33.7c0-87.1 39.4-127.5 125-127.5 16.2 0 44.2 3.2 55.7 6.4V172c-6-.6-16.5-1-29.6-1-42 0-58.2 15.9-58.2 57.2V256h83.6l-14.4 78.2H287v175.9C413.8 494.8 512 386.9 512 256h0z"
                                ></path>
                            </svg>
                        </Link>
                        <Link href={""} className={styles.social}>
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                width="1em"
                                height="1em"
                                fill="currentColor"
                                stroke="currentColor"
                                strokeWidth="0"
                                viewBox="0 0 448 512"
                            >
                                <path
                                    stroke="none"
                                    d="M224.1 141c-63.6 0-114.9 51.3-114.9 114.9s51.3 114.9 114.9 114.9S339 319.5 339 255.9 287.7 141 224.1 141zm0 189.6c-41.1 0-74.7-33.5-74.7-74.7s33.5-74.7 74.7-74.7 74.7 33.5 74.7 74.7-33.6 74.7-74.7 74.7zm146.4-194.3c0 14.9-12 26.8-26.8 26.8-14.9 0-26.8-12-26.8-26.8s12-26.8 26.8-26.8 26.8 12 26.8 26.8zm76.1 27.2c-1.7-35.9-9.9-67.7-36.2-93.9-26.2-26.2-58-34.4-93.9-36.2-37-2.1-147.9-2.1-184.9 0-35.8 1.7-67.6 9.9-93.9 36.1s-34.4 58-36.2 93.9c-2.1 37-2.1 147.9 0 184.9 1.7 35.9 9.9 67.7 36.2 93.9s58 34.4 93.9 36.2c37 2.1 147.9 2.1 184.9 0 35.9-1.7 67.7-9.9 93.9-36.2 26.2-26.2 34.4-58 36.2-93.9 2.1-37 2.1-147.8 0-184.8zM398.8 388c-7.8 19.6-22.9 34.7-42.6 42.6-29.5 11.7-99.5 9-132.1 9s-102.7 2.6-132.1-9c-19.6-7.8-34.7-22.9-42.6-42.6-11.7-29.5-9-99.5-9-132.1s-2.6-102.7 9-132.1c7.8-19.6 22.9-34.7 42.6-42.6 29.5-11.7 99.5-9 132.1-9s102.7-2.6 132.1 9c19.6 7.8 34.7 22.9 42.6 42.6 11.7 29.5 9 99.5 9 132.1s2.7 102.7-9 132.1z"
                                ></path>
                            </svg>
                        </Link>
                        <Link href={""} className={styles.social}>
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                width="1em"
                                height="1em"
                                fill="currentColor"
                                stroke="currentColor"
                                strokeWidth="0"
                                viewBox="0 0 576 512"
                            >
                                <path
                                    stroke="none"
                                    d="M549.655 124.083c-6.281-23.65-24.787-42.276-48.284-48.597C458.781 64 288 64 288 64S117.22 64 74.629 75.486c-23.497 6.322-42.003 24.947-48.284 48.597-11.412 42.867-11.412 132.305-11.412 132.305s0 89.438 11.412 132.305c6.281 23.65 24.787 41.5 48.284 47.821C117.22 448 288 448 288 448s170.78 0 213.371-11.486c23.497-6.321 42.003-24.171 48.284-47.821 11.412-42.867 11.412-132.305 11.412-132.305s0-89.438-11.412-132.305zm-317.51 213.508V175.185l142.739 81.205-142.739 81.201z"
                                ></path>
                            </svg>
                        </Link>
                    </div>
                </div>
                <div className={styles.line}/>
                <div className={styles.bottom}>
                    <p className={"text-typeSecondary"}>
                        &copy;2024 Azv Motors. Все права защищены.
                    </p>
                    <div className={styles.links}>
                        <Link href={""}>Политика конфиденциальности</Link>
                        <Link href={""}>Оферта</Link>
                    </div>
                </div>
            </div>
        </footer>
    );
};
