import styles from "./styles.module.scss";
import classNames from "classnames";
import {BannerAbout} from "widgets/banner-about";
import {BannerWhyUs} from "widgets/banner-why-us";

export const About = () => {
    return (
        <main className={classNames("wrapper", styles.container)}>
            <div className={styles.content}>
                <BannerAbout/>
                <BannerWhyUs/>
            </div>
        </main>
    );
};
