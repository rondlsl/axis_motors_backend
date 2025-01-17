import styles from "./styles.module.scss";
import { BannerMain } from "widgets/banner-main";
import classNames from "classnames";
import { BannerHowItWork } from "widgets/banner-how-it-work";
import { LogosCarousel } from "shared/ui";
import { BannerWhyUs } from "widgets/banner-why-us";
import { BannerReviews } from "widgets/banner-reviews";
import { BannerDownload } from "widgets/banner-download";

export const Main = () => {
  return (
    <>
      <div className={classNames("wrapper", styles.container)}>
        <BannerMain />
        <BannerHowItWork />
      </div>
      <LogosCarousel />
      <div className={classNames("wrapper")}>
        <BannerWhyUs />
      </div>
      {/*<div className={styles.reviews}>*/}
      {/*  <div className={"wrapper"}>*/}
      {/*    <BannerReviews />*/}
      {/*  </div>*/}
      {/*</div>*/}
      <div className={classNames("wrapper")}>
        <BannerDownload />
      </div>
    </>
  );
};
