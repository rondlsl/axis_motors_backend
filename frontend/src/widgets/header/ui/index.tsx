"use client";

import {Logo, Button} from "shared/ui";
import styles from "./styles.module.scss";
import classNames from "classnames";
import {navContent} from "shared/common";
import Link from "next/link";
import {useState} from "react";
import {useRouter} from "next/navigation";
import Image from "next/image";
import {User, Menu} from "lucide-react";

export const Header = () => {
    const router = useRouter();
    const [isMobileNavActive, setIsMobileNavActive] = useState(false);

    const toggleMobileNav = () => {
        setIsMobileNavActive((prevState) => !prevState);
    };

    return (
        <header className={classNames(styles.container, "bg-bgSecondary")}>
            <div className={classNames(styles.content, "wrapper")}>
                <Logo/>
                <ul className={styles.nav}>
                    {navContent.map((i, index) => (
                        <li key={index} className={styles.li}>
                            <Link href={i.href} className={styles.link}>
                                {i.name}
                            </Link>
                        </li>
                    ))}
                </ul>
                <div className={styles.buttons}>
                    <Button mode={"icon"} onClick={() => router.push("/login")}>
                        <User
                            width={24}
                            height={24}
                        />
                    </Button>
                    <Button
                        mode={"icon"}
                        className={styles.burger}
                        onClick={toggleMobileNav}
                    >
                        <Menu
                            width={24}
                            height={24}
                        />
                    </Button>
                </div>
            </div>
            <div
                className={classNames(
                    styles.mobileNav,
                    isMobileNavActive && styles.active,
                )}
            >
                <div className={classNames("wrapper", styles.mobileNavContent)}>
                    <ul className={styles.ul}>
                        {navContent.map((i, index) => (
                            <li
                                key={index}
                                className={styles.li}
                                onClick={() => {
                                    toggleMobileNav();
                                    router.push(i.href);
                                }}
                            >
                                {i.name}
                            </li>
                        ))}
                    </ul>
                    <Button
                        mode={"icon"}
                        className={styles.burger}
                        onClick={toggleMobileNav}
                    >
                        <Image
                            width={24}
                            height={24}
                            src="/img/utils/close.svg"
                            alt="Close"
                        />
                    </Button>
                </div>
            </div>
        </header>
    );
};
