"""GraphQL documents for https://www.coles.com.au/api/graphql, copied verbatim
from the site's own JS bundles (2026-10-05) with their fragments inlined.
The gateway is not a persisted-query endpoint: it executes whatever document
is posted, so these only need refreshing when Coles removes a field.

    DOCUMENTS[operation_name] -> query text
"""

DOCUMENTS = {}

DOCUMENTS["GetProductDetails"] = """
query GetProductDetails($storeId: BrandedId!, $productId: String!, $shoppingMethod: ShoppingMethod, $useV2NipAndAllergens: Boolean) {
  product(
    storeId: $storeId
    productId: $productId
    shoppingMethod: $shoppingMethod
    useV2NipAndAllergens: $useV2NipAndAllergens
  ) {
    id
    name
    brand
    description
    size
    imageUris {
      altText
      type
      uri
    }
    images {
      thumb {
        path
        description
      }
      zoom {
        path
        description
      }
      full {
        path
        description
      }
    }
    restrictions {
      retailLimit
      promotionalLimit
      liquorAgeRestrictionFlag
      tobaccoAgeRestrictionFlag
      delivery
      restrictedByOrganisation
    }
    availability
    availabilityStatus
    minGuarantee
    merchandiseHeir {
      tradeProfitCentre
      categoryGroup
      category
      subCategory
      className
    }
    onlineHeirs {
      aisle
      category
      subCategory
      categoryId
      aisleId
      subCategoryId
    }
    associatedProductId
    continuity {
      continuityPromotionId
      creditsToRedeem
      bonusAvailable
      bonusTimes
      bonusPromoName
      bonusRoundelDisplayable
      bonusRoundelDescription
    }
    lifestyle
    countryOfOrigin {
      logoRequired
      barcodeRequired
      descriptionRequired
      country
      barcodePercentage
      statement
      description
    }
    lastUpdated
    locations {
      aisleSide
      description
      facing
      aisle
      order
      shelf
    }
    additionalInfo {
      title
      description
    }
    excludeFromSubstitution
    brandDetails {
      id
      name
      seoToken
    }
    collectableCampaign
    disclaimers
    internalDescription
    longDescription
    nutrition {
      title
      servingsPerPackage
      servingSize
      dailyIntakeDisclaimer
      breakdown {
        title
        subtitle
        disclaimer
        nutrients {
          nutrient
          value
          dailyIntakeInfo
          nutrientDisplayOrder
        }
      }
    }
    nutritionalClaims
    pricing {
      now
      was
      saveAmount
      saveStatement
      unit {
        quantity
        ofMeasureQuantity
        ofMeasureUnits
        price
        ofMeasureType
        isWeighted
        isIncremental
      }
      comparable
      promotionType
      onlineSpecial
      multiBuyPromotion {
        type
        id
        minQuantity
        reward
        unitPriceDisplay
        instruction
      }
      priceDescription
      savePercent
      specialType
      offerDescription
    }
    gtin
    ...productVariationsFields
  }
}
fragment productVariationsFields on Product {
  variations {
    total
    byVarieties {
      ...variationProductFields
    }
    bySizes {
      ...variationProductFields
    }
  }
}
fragment variationProductFields on BaseProduct {
  id
  name
  brand
  description
  size
  imageUris {
    altText
    type
    uri
  }
  images {
    thumb {
      path
      description
    }
    zoom {
      path
      description
    }
    full {
      path
      description
    }
  }
  restrictions {
    retailLimit
    promotionalLimit
    liquorAgeRestrictionFlag
    tobaccoAgeRestrictionFlag
    delivery
  }
  availability
  availabilityType
  availabilityStatus
  merchandiseHeir {
    tradeProfitCentre
    categoryGroup
    category
    subCategory
    className
  }
  onlineHeirs {
    aisle
    category
    subCategory
    categoryId
    aisleId
    subCategoryId
  }
  associatedProductId
  continuity {
    continuityPromotionId
    creditsToRedeem
    bonusAvailable
    bonusTimes
    bonusPromoName
    bonusRoundelDisplayable
    bonusRoundelDescription
  }
  pricing {
    now
    was
    saveAmount
    saveStatement
    unit {
      quantity
      ofMeasureQuantity
      ofMeasureUnits
      price
      ofMeasureType
      isWeighted
      isIncremental
    }
    comparable
    promotionType
    onlineSpecial
    multiBuyPromotion {
      type
      id
      minQuantity
      reward
      unitPriceDisplay
      instruction
    }
    priceDescription
    savePercent
    specialType
    offerDescription
  }
}
"""

DOCUMENTS["GetProductsInfo"] = """
query GetProductsInfo($productIds: [String!]!, $brandedStoreId: BrandedId!, $shoppingMethod: ShoppingMethod, $filters: ProductsInfoFilters) {
  productsInfo(
    productIds: $productIds
    brandedStoreId: $brandedStoreId
    shoppingMethod: $shoppingMethod
    filters: $filters
  ) {
    count: noOfResults
    invalidProductIds: invalidProducts
    results {
      ...productsInfoFields
    }
  }
}
fragment productsInfoFields on InfoProduct {
  id
  name
  brand
  description
  internalDescription
  size
  imageUris {
    altText
    type
    uri
  }
  restrictions {
    retailLimit
    promotionalLimit
    liquorAgeRestrictionFlag
    tobaccoAgeRestrictionFlag
    delivery
    restrictedByOrganisation
  }
  continuity {
    continuityPromotionId
    creditsToRedeem
    bonusAvailable
    bonusTimes
    bonusPromoName
    bonusRoundelDisplayable
    bonusRoundelDescription
  }
  collectableCampaign
  lastUpdated
  availability
  availabilityType
  availabilityStatus
  merchandiseHeir {
    tradeProfitCentre
    categoryGroup
    category
    subCategory
    className
  }
  onlineHeirs {
    aisle
    category
    subCategory
    categoryId
    aisleId
    subCategoryId
  }
  pricing {
    now
    was
    saveAmount
    saveStatement
    unit {
      quantity
      ofMeasureQuantity
      ofMeasureUnits
      price
      ofMeasureType
      isWeighted
      isIncremental
    }
    comparable
    promotionType
    onlineSpecial
    multiBuyPromotion {
      type
      id
      minQuantity
      reward
      unitPriceDisplay
      instruction
    }
    priceDescription
    savePercent
    specialType
    offerDescription
  }
  minGuarantee
}
"""

DOCUMENTS["GetProductCategories"] = """
query GetProductCategories($storeId: BrandedId!, $withCampaignLinks: Boolean!, $campaignCount: Int) {
  productCategories(
    storeId: $storeId
    withCampaignLinks: $withCampaignLinks
    campaignCount: $campaignCount
  ) {
    ...productCategoriesFields
  }
}
fragment productCategoriesFields on ProductCategories {
  excludedCategoryIds
  catalogGroupView {
    ...catalogGroupFields
    catalogGroupView {
      ...catalogGroupFields
      catalogGroupView {
        ...catalogGroupFields
      }
    }
  }
}
fragment catalogGroupFields on ProductCategory {
  id
  level
  name
  originalName
  productCount
  seoToken
  type
  subType
}
"""

DOCUMENTS["FindStores"] = """
query FindStores($latitude: Float!, $longitude: Float!, $brandIds: [BrandId!], $count: Float!, $distance: Float) {
  stores(
    latitude: $latitude
    longitude: $longitude
    brandIds: $brandIds
    count: $count
    distance: $distance
    isTrading: true
  ) {
    results {
      distance
      store {
        ...storeFields
        hours {
          ...hoursTodayFields
        }
        nextDoorStores: nearby(brandIds: [LQR, FCL, VIN], count: 1) {
          ...nextDoorStoreFields
        }
      }
    }
  }
}
fragment storeFields on Store {
  id
  name
  address {
    state
    suburb
    addressLine
    postcode
  }
  position {
    latitude
    longitude
  }
  brand {
    name
    storeFinderId
    id
  }
  phone
  isTrading
  services {
    name
    type
  }
}
fragment hoursTodayFields on Hours {
  today {
    time
    holidayReason
    isOpen
  }
}
fragment nextDoorStoreFields on StoreDistanceCollection {
  results {
    store {
      id
      name
      brand {
        id
        storeFinderId
      }
    }
  }
}
"""

DOCUMENTS["GetStoreDetails"] = """
query GetStoreDetails($id: BrandedId!) {
  store(id: $id) {
    ...storeFields
    hours {
      ...hoursTodayFields
      ...hoursScheduleFields
      ...hoursExceptionsFields
    }
    collectionPoints {
      results {
        id
        type
      }
    }
  }
}
fragment storeFields on Store {
  id
  name
  address {
    state
    suburb
    addressLine
    postcode
  }
  position {
    latitude
    longitude
  }
  brand {
    name
    storeFinderId
    id
  }
  phone
  isTrading
  services {
    name
    type
  }
}
fragment hoursTodayFields on Hours {
  today {
    time
    holidayReason
    isOpen
  }
}
fragment hoursScheduleFields on Hours {
  schedule {
    daysOfWeek
    time
  }
}
fragment hoursExceptionsFields on Hours {
  exceptions {
    time
    reason
    date
    isOpen
  }
}
"""

DOCUMENTS["GetStoreLocationSuggestions"] = """
query GetStoreLocationSuggestions($term: String!, $count: Int) {
  localitySearch(term: $term, count: $count) {
    results {
      postcode
      state
      suburb
      latitude
      longitude
    }
  }
}
"""

DOCUMENTS["SearchRecipes"] = """
query SearchRecipes($searchTerm: String!, $page: Int, $pageSize: Int, $isExternalPublished: Boolean, $mustHaveImage: Boolean, $storeIdentifier: String, $providers: [String!], $randomize: Boolean, $exclude: [String!], $allergies: [String!], $diets: [String!], $recipeIds: [String!], $orderBy: [String!], $orderByType: String, $minPrice: Float, $maxPrice: Float, $minPortionPrice: Float, $maxPortionPrice: Float, $minConsumptionPrice: Float, $maxConsumptionPrice: Float, $minConsumptionPortionPrice: Float, $maxConsumptionPortionPrice: Float, $minCookingTime: Int, $maxCookingTime: Int, $tags: [String!]) {
  searchRecipes(
    searchTerm: $searchTerm
    page: $page
    pageSize: $pageSize
    isExternalPublished: $isExternalPublished
    mustHaveImage: $mustHaveImage
    storeIdentifier: $storeIdentifier
    providers: $providers
    randomize: $randomize
    exclude: $exclude
    allergies: $allergies
    diets: $diets
    recipeIds: $recipeIds
    orderBy: $orderBy
    orderByType: $orderByType
    minPrice: $minPrice
    maxPrice: $maxPrice
    minPortionPrice: $minPortionPrice
    maxPortionPrice: $maxPortionPrice
    minConsumptionPrice: $minConsumptionPrice
    maxConsumptionPrice: $maxConsumptionPrice
    minConsumptionPortionPrice: $minConsumptionPortionPrice
    maxConsumptionPortionPrice: $maxConsumptionPortionPrice
    minCookingTime: $minCookingTime
    maxCookingTime: $maxCookingTime
    tags: $tags
  ) {
    page
    pageSize
    noOfResults
    results {
      id
      preparationTime
      slug
      title
      description
      portions
      sourceUrl
      images {
        type
        url
      }
      cookingTime
      price {
        total
        portion
        consumptionTotal
        consumptionPortion
      }
      nutrition {
        calories
        carbohydrates
        fat
        protein
        sugar
        fiber
        updatedAt
      }
      ingredients {
        id
        name
        subTitle
        imageUrl
        amount
        unit
      }
      steps {
        title
        text
        sortOrder
      }
      stores {
        identifier
        name
      }
      tags {
        id
        alias
        name
      }
      sourceData
      totalTime
    }
  }
}
"""

DOCUMENTS["SearchRecipesByIds"] = """
query SearchRecipesByIds($recipeIds: [String!]!, $page: Int, $pageSize: Int, $randomize: Boolean, $orderBy: [String!], $orderByType: String) {
  searchRecipesByIds(
    recipeIds: $recipeIds
    page: $page
    pageSize: $pageSize
    randomize: $randomize
    orderBy: $orderBy
    orderByType: $orderByType
  ) {
    page
    pageSize
    noOfResults
    results {
      id
      preparationTime
      slug
      title
      description
      portions
      sourceUrl
      images {
        type
        url
      }
      cookingTime
      price {
        total
        portion
        consumptionTotal
        consumptionPortion
      }
      nutrition {
        calories
        carbohydrates
        fat
        protein
        sugar
        fiber
        updatedAt
      }
      ingredients {
        id
        name
        subTitle
        imageUrl
        amount
        unit
      }
      steps {
        title
        text
        sortOrder
      }
      stores {
        identifier
        name
      }
      tags {
        id
        alias
        name
      }
      sourceData
      totalTime
    }
  }
}
"""

DOCUMENTS["StoreRange"] = """
query StoreRange($productIds: [ID!]!) {
  storeRange(productIds: $productIds) {
    stateCode
    products {
      productId
      name
      brand
      size
      stores {
        storeId
        storeName
      }
    }
  }
}
"""

DOCUMENTS["PublicHolidays"] = """
query PublicHolidays($state: String) {
  publicHolidays(state: $state) {
    date
    name
    state
  }
}
"""
